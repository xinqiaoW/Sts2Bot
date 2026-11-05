"""Train one model on a frozen snapshot and write a self-describing artifact.

Usage::

    python -m train.train --snapshot data/train-snapshots/<stamp> --model tabm --device cuda:0

Artifacts (``checkpoints/train/<snapshot>/<model>/``):

* ``artifact.json``   model name/kind, hyper-parameters, snapshot manifest summary,
                      teachers, trained targets, metrics summary
* ``vocab.json``      frozen feature/symbol vocabulary (required for inference)
* ``weights.pt``      torch state dict, or ``regression.lgb.txt`` + ``death.lgb.txt``
* ``metrics.json``    per-split metrics (overall / by kind / by act / by source)
* ``history.json``    per-epoch validation curve
* ``predictions.parquet`` row-level predictions for every split
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import random
import subprocess
import time

import numpy as np
import pandas as pd
import torch
from torch import nn

from damage_model.schema import canonical

from . import ROOT
from .data import Dataset, SPLITS, load_catalog
from .metrics import evaluate, summarize
from .models import ALL_MODELS, BOOSTER_MODELS, TORCH_MODELS, build_torch_model, input_kind

ARTIFACT_VERSION = 2


def log_line(message):
    print(message, flush=True)


def seed_everything(seed):
    random.seed(seed); np.random.seed(seed); torch.manual_seed(seed)


def load_model_config(path, name, overrides=None):
    config = json.loads(Path(path).read_text(encoding='utf-8'))
    hparams = {**config['defaults'], **config['models'].get(name, {}), **(overrides or {})}
    return hparams


def code_provenance():
    files = list((ROOT/'train').glob('*.py')) + list((ROOT/'train/models').glob('*.py'))
    files += [ROOT/'damage_model'/name for name in ['encoding.py', 'schema.py', 'card_state.py', 'catalog.py', 'model.py']]
    record = {'files': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    for key, command in [('branch', ['git', 'branch', '--show-current']), ('commit', ['git', 'rev-parse', 'HEAD'])]:
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True)
        record[key] = result.stdout.strip() if result.returncode == 0 else None
    return record


class DeviceData:
    """Pair encodings and row labels resident on one device."""

    def __init__(self, dataset: Dataset, kind, device, *, use_aux=False, defer_cuda=False):
        self.device = torch.device(device)
        self.kind = kind
        self._deferred_device = self.device if defer_cuda else None
        target_dev = torch.device('cpu') if defer_cuda else self.device
        enc = dataset.encoded
        if kind == 'sparse':
            csr = enc['sparse']
            self.n_features = csr.shape[1]
            nnz = np.diff(csr.indptr)
            width = int(nnz.max()) if len(nnz) else 1
            indices = np.full((csr.shape[0], width), self.n_features, dtype=np.int64)  # padding column
            values = np.zeros((csr.shape[0], width), dtype=np.float32)
            for i in range(csr.shape[0]):
                start, end = csr.indptr[i], csr.indptr[i + 1]
                indices[i, :end - start] = csr.indices[start:end]
                values[i, :end - start] = csr.data[start:end]
            self.indices = torch.from_numpy(indices).to(target_dev)
            self.values = torch.from_numpy(values).to(target_dev)
        else:
            self.symbols = torch.from_numpy(enc['symbols'].astype(np.int64)).to(target_dev)
            self.numerics = torch.from_numpy(enc['numerics']).to(target_dev)

        self.aux_mu = np.zeros(9, dtype=np.float32)
        self.aux_sd = np.ones(9, dtype=np.float32)
        aux_full_y, aux_full_mask = None, None
        if use_aux:
            import pyarrow.parquet as pq
            from .aux_labels import AUX_COLUMNS, build_snapshot_aux_parquet
            aux_path = build_snapshot_aux_parquet(dataset.snapshot.directory)
            aux_df = pq.read_table(aux_path).to_pandas()
            n_total = len(dataset.rows)
            raw_aux = np.zeros((n_total, 1 + len(AUX_COLUMNS)), dtype=np.float32)
            mask_aux = np.zeros((n_total, 1 + len(AUX_COLUMNS)), dtype=np.float32)
            ft = dataset.rows['finished_turn'].fillna(0).to_numpy(dtype=np.float32)
            raw_aux[:, 0] = np.log1p(np.maximum(0.0, ft))
            mask_aux[:, 0] = (ft > 0).astype(np.float32)
            has_tr = aux_df['has_trace'].to_numpy(dtype=bool)
            for ci, col in enumerate(AUX_COLUMNS, start=1):
                vals = aux_df[col].to_numpy(dtype=np.float32)
                valid = has_tr & np.isfinite(vals)
                raw_aux[valid, ci] = vals[valid]
                mask_aux[valid, ci] = 1.0
            # Z-score normalize using training split valid statistics
            self.aux_mu = np.zeros(raw_aux.shape[1], dtype=np.float32)
            self.aux_sd = np.ones(raw_aux.shape[1], dtype=np.float32)
            train_pair_mask = (dataset.pairs.split.to_numpy()[dataset.rows.pair.to_numpy()] == 'train')
            for j in range(raw_aux.shape[1]):
                v = (mask_aux[:, j] > 0.5) & train_pair_mask
                if v.any():
                    mu = float(raw_aux[v, j].mean())
                    sd = float(raw_aux[v, j].std())
                    if sd < 1e-6:
                        sd = 1.0
                    self.aux_mu[j] = mu
                    self.aux_sd[j] = sd
                    raw_aux[:, j] = np.where(mask_aux[:, j] > 0.5, (raw_aux[:, j] - mu) / sd, 0.0)
            aux_full_y, aux_full_mask = raw_aux, mask_aux

        self.rows = {}
        pair_splits = dataset.pairs.split.to_numpy()[dataset.rows.pair.to_numpy()]
        for split in SPLITS:
            rows = dataset.split_rows(split)
            self.rows[split] = {k: torch.as_tensor(rows[c].to_numpy(), device=target_dev)
                                for k, c in (('pair', 'pair'), ('y', 'y'), ('died', 'died'), ('weight', 'weight'))}
            self.rows[split]['pair'] = self.rows[split]['pair'].long()
            if aux_full_y is not None:
                smask = (pair_splits == split)
                self.rows[split]['aux_y'] = torch.from_numpy(aux_full_y[smask]).to(target_dev)
                self.rows[split]['aux_mask'] = torch.from_numpy(aux_full_mask[smask]).to(target_dev)

    def move_to_device(self):
        if getattr(self, '_deferred_device', None) is None:
            return
        if self.kind == 'sparse':
            self.indices = self.indices.to(self.device)
            self.values = self.values.to(self.device)
        else:
            self.symbols = self.symbols.to(self.device)
            self.numerics = self.numerics.to(self.device)
        for split in SPLITS:
            for k, v in self.rows[split].items():
                self.rows[split][k] = v.to(self.device)
        self._deferred_device = None

    def batch(self, pairs):
        if self.kind == 'sparse':
            x = torch.zeros(len(pairs), self.n_features + 1, device=self.device)
            x.scatter_add_(1, self.indices[pairs], self.values[pairs])
            return (x[:, :-1],)
        return (self.symbols[pairs], self.numerics[pairs])


def forward(model, data: DeviceData, pairs):
    out = model(*data.batch(pairs))
    return out  # (B, 2) or (B, k, 2)


def loss_fn(out, y, died, weight, death_weight):
    if out.ndim == 3:  # ensemble members are trained independently, then averaged
        y, died, weight = y[:, None], died[:, None], weight[:, None]
    mse = (out[..., 0] - y) ** 2
    bce = nn.functional.binary_cross_entropy_with_logits(out[..., 1], died.expand_as(out[..., 1]), reduction='none')
    per_row = (mse + death_weight * bce)
    if per_row.ndim == 2:
        per_row = per_row.mean(dim=1)
        weight = weight[:, 0]
    return (per_row * weight).sum() / weight.sum()


@torch.no_grad()
def predict_rows(model, data: DeviceData, split, batch_size=4096):
    model.eval()
    pairs = data.rows[split]['pair']
    unique_pairs, inverse = torch.unique(pairs, sorted=True, return_inverse=True)
    means, deaths = [], []
    # Different battle seeds share the same model input. Evaluate each input
    # once, then restore every row for the original weighted metrics.
    for start in range(0, len(unique_pairs), batch_size):
        out = forward(model, data, unique_pairs[start:start + batch_size])
        if out.ndim == 3:
            out = torch.stack([out[..., 0].mean(dim=1), torch.sigmoid(out[..., 1]).mean(dim=1)], dim=-1)
        else:
            out = torch.stack([out[:, 0], torch.sigmoid(out[:, 1])], dim=-1)
        means.append(out[:, 0]); deaths.append(out[:, 1])
    return torch.cat(means)[inverse].cpu().numpy(), torch.cat(deaths)[inverse].cpu().numpy()


def train_torch(name, dataset, hparams, device, output, log):
    seed_everything(hparams['seed'])
    use_aux = bool(hparams.get('aux_supervision', False))
    use_step = bool(hparams.get('step_supervision', False))
    aux_loss_weight = float(hparams.get('aux_loss_weight', 0.05))
    step_loss_weight = float(hparams.get('step_loss_weight', 0.25))
    step_imm_weight = float(hparams.get('step_imm_weight', 0.08))
    step_every = int(hparams.get('step_every', 1))
    data = DeviceData(dataset, input_kind(name), device, use_aux=use_aux, defer_cuda=use_step)
    streamer = None
    if use_step:
        from .step_snapshots import StepBatchStreamer, augment_vocab_for_steps
        augment_vocab_for_steps(dataset.vocab, dataset.snapshot.directory)
        streamer = StepBatchStreamer(
            dataset,
            data.aux_mu,
            data.aux_sd,
            batch_size=int(hparams.get('step_batch_size', 1024)),
            max_steps_per_battle=int(hparams.get('max_steps_per_battle', 6)),
            num_workers=int(hparams.get('step_workers', 8)),
            seed=int(hparams['seed']),
        )
        data.move_to_device()
        log(json.dumps({
            'event': 'step_streamer',
            'train_trace_battles': streamer.n_train_trace_battles,
            'chunks': streamer.n_chunks,
            'vocab_symbols': dataset.vocab.n_symbols,
        }))
    model = build_torch_model(name, dataset.vocab, hparams).to(device)
    if hparams.get('init_weights'):
        init_w = Path(hparams['init_weights'])
        old_sd = torch.load(init_w, map_location=device, weights_only=True)
        try:
            model.load_state_dict(old_sd)
            log(json.dumps({'event': 'init_weights', 'mode': 'exact', 'path': str(init_w)}))
        except RuntimeError:
            cur_sd = model.state_dict()
            copied = 0
            old_vocab_path = init_w.parent / 'vocab.json'
            if old_vocab_path.exists() and 'embed.symbols.weight' in old_sd:
                old_syms = json.loads(old_vocab_path.read_text(encoding='utf-8')).get('symbols', [])
                old_emb = old_sd['embed.symbols.weight']
                new_emb = cur_sd['embed.symbols.weight']
                for oi, s_name in enumerate(old_syms):
                    ni = dataset.vocab.symbol_index.get(s_name)
                    if ni is not None and oi < old_emb.shape[0] and ni < new_emb.shape[0]:
                        new_emb[ni].copy_(old_emb[oi])
                copied += 1
            for k, v in old_sd.items():
                if k == 'embed.symbols.weight':
                    continue
                if k in cur_sd:
                    if cur_sd[k].shape == v.shape:
                        cur_sd[k].copy_(v)
                        copied += 1
                    elif cur_sd[k].ndim == 2 and v.ndim == 2 and cur_sd[k].shape[0] == v.shape[0] and cur_sd[k].shape[1] > v.shape[1]:
                        cur_sd[k][:, :v.shape[1]].copy_(v)
                        copied += 1
                elif k == 'embed.numerics.weight' and 'embed.numerics.0.weight' in cur_sd:
                    tgt = cur_sd['embed.numerics.0.weight']
                    if tgt.shape[0] == v.shape[0] and tgt.shape[1] >= v.shape[1]:
                        tgt[:, :v.shape[1]].copy_(v)
                        copied += 1
                elif k == 'embed.numerics.bias' and 'embed.numerics.0.bias' in cur_sd:
                    if cur_sd['embed.numerics.0.bias'].shape == v.shape:
                        cur_sd['embed.numerics.0.bias'].copy_(v)
                        copied += 1
            model.load_state_dict(cur_sd)
            log(json.dumps({'event': 'init_weights', 'mode': 'mapped_warmstart', 'copied_tensors': copied, 'path': str(init_w)}))
    n_params = sum(p.numel() for p in model.parameters())
    log(json.dumps({'event': 'model', 'name': name, 'parameters': n_params, 'device': str(device)}))
    optimizer = torch.optim.AdamW(model.parameters(), lr=hparams['lr'], weight_decay=hparams['weight_decay'])
    scheduler = (
        torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=hparams['epochs'], eta_min=hparams['lr'] * 0.05)
        if hparams.get('cosine_lr', False)
        else None
    )
    train_rows = data.rows['train']
    n = len(train_rows['pair'])
    best, best_state, best_epoch, history = float('inf'), None, 0, []
    validation = dataset.split_rows('validation')
    prediction_batch_size = hparams.get('prediction_batch_size', 4096)
    started = time.time()
    try:
        for epoch in range(1, hparams['epochs'] + 1):
            model.train()
            order = torch.randperm(n, device=data.device)
            total, count = 0.0, 0
            step_total, step_count = 0.0, 0
            for step_idx, indices in enumerate(order.split(hparams['batch_size'])):
                if use_aux and getattr(model, 'aux_head', None) is not None:
                    out, aux_pred = model(*data.batch(train_rows['pair'][indices]), return_aux=True)
                    primary = loss_fn(out, train_rows['y'][indices], train_rows['died'][indices], train_rows['weight'][indices], hparams['death_loss_weight'])
                    ay = train_rows['aux_y'][indices]
                    am = train_rows['aux_mask'][indices]
                    adiff = nn.functional.smooth_l1_loss(aux_pred, ay, reduction='none', beta=0.5) * am
                    arow = adiff.sum(dim=1) / am.sum(dim=1).clamp_min(1.0)
                    w = train_rows['weight'][indices]
                    aloss = (arow * w).sum() / w.sum()
                    loss = primary + aux_loss_weight * aloss
                else:
                    out = forward(model, data, train_rows['pair'][indices])
                    loss = loss_fn(out, train_rows['y'][indices], train_rows['died'][indices], train_rows['weight'][indices], hparams['death_loss_weight'])
                optimizer.zero_grad(set_to_none=True)
                loss.backward()
                total_step_loss_val = float(loss.detach())
                if streamer is not None and (step_idx % step_every == 0):
                    s_syms, s_nums, s_y, s_died, s_aux, s_imm, s_w = streamer.next_batch(data.device)
                    s_out, s_aux_pred, s_imm_pred = model(s_syms, s_nums, return_step=True)
                    s_primary = loss_fn(s_out, s_y, s_died, s_w, hparams['death_loss_weight'])
                    s_aloss = 0.0
                    if s_aux_pred is not None:
                        s_adiff = nn.functional.smooth_l1_loss(s_aux_pred, s_aux, reduction='none', beta=0.5).mean(dim=1)
                        s_aloss = (s_adiff * s_w).sum() / s_w.sum().clamp_min(1e-6)
                    s_iloss = 0.0
                    if s_imm_pred is not None:
                        s_idiff = nn.functional.smooth_l1_loss(s_imm_pred, s_imm, reduction='none', beta=0.5).mean(dim=1)
                        s_iloss = (s_idiff * s_w).sum() / s_w.sum().clamp_min(1e-6)
                    s_loss = s_primary + aux_loss_weight * s_aloss + step_imm_weight * s_iloss
                    (step_loss_weight * s_loss).backward()
                    s_val = float(s_loss.detach())
                    total_step_loss_val += step_loss_weight * s_val
                    step_total += s_val * len(s_y)
                    step_count += len(s_y)
                nn.utils.clip_grad_norm_(model.parameters(), 5.0)
                optimizer.step()
                total += total_step_loss_val * len(indices); count += len(indices)
            if scheduler is not None:
                scheduler.step()
            mean, death = predict_rows(model, data, 'validation', batch_size=prediction_batch_size)
            metrics = evaluate(validation, mean, death, groupers=())['overall']
            record = {'epoch': epoch, 'train_loss': total / count, 'validation_pair_mae_hp': metrics['pair_mae_hp'],
                      'validation_row_mae_hp': metrics['row_mae_hp'], 'validation_row_rmse_hp': metrics['row_rmse_hp'],
                      'validation_death_brier': metrics['death_brier'], 'elapsed_s': round(time.time() - started, 1)}
            if step_count > 0:
                record['step_train_loss'] = round(step_total / step_count, 6)
            history.append(record)
            log(json.dumps(record))
            (output / 'history.json').write_text(json.dumps(history, ensure_ascii=False), encoding='utf-8')
            if metrics['pair_mae_hp'] < best:
                best, best_epoch = metrics['pair_mae_hp'], epoch
                best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
                torch.save(best_state, output / 'weights.pt')
            elif epoch - best_epoch >= hparams['patience']:
                log(json.dumps({'event': 'early_stop', 'epoch': epoch, 'best_epoch': best_epoch}))
                break
    finally:
        if streamer is not None:
            streamer.close()
    model.load_state_dict(best_state)
    torch.save(best_state, output / 'weights.pt')
    predictions = {split: predict_rows(model, data, split, batch_size=prediction_batch_size) for split in SPLITS}
    return predictions, history, {'best_epoch': best_epoch, 'parameters': n_params}


def train_lightgbm(dataset, hparams, output, log):
    import lightgbm as lgb
    seed_everything(hparams['seed'])
    rows = {split: dataset.split_rows(split) for split in SPLITS}
    X = {split: dataset.row_matrix(rows[split]) for split in SPLITS}
    boosters, history = {}, {}
    for head, label in (('regression', 'y'), ('death', 'died')):
        params = {**hparams[head], 'num_threads': hparams['num_threads'], 'seed': hparams['seed']}
        train_set = lgb.Dataset(X['train'], rows['train'][label].to_numpy(), weight=rows['train'].weight.to_numpy())
        valid_set = lgb.Dataset(X['validation'], rows['validation'][label].to_numpy(), weight=rows['validation'].weight.to_numpy(), reference=train_set)
        record = {}
        booster = lgb.train(params, train_set, num_boost_round=hparams['max_rounds'], valid_sets=[valid_set], valid_names=['validation'],
                            callbacks=[lgb.early_stopping(hparams['early_stopping_rounds'], verbose=False), lgb.record_evaluation(record),
                                       lgb.log_evaluation(period=100)])
        boosters[head] = booster
        metric = next(iter(record['validation']))
        history[head] = {'metric': metric, 'best_iteration': booster.best_iteration, 'curve': record['validation'][metric]}
        booster.save_model(str(output / f'{head}.lgb.txt'), num_iteration=booster.best_iteration)
        log(json.dumps({'event': 'booster', 'head': head, 'best_iteration': booster.best_iteration,
                        'validation_' + metric: record['validation'][metric][booster.best_iteration - 1]}))
    predictions = {}
    for split in SPLITS:
        pair_ids, inverse = np.unique(rows[split].pair.to_numpy(), return_inverse=True)
        inputs = dataset.encoded['sparse'][pair_ids]
        mean = boosters['regression'].predict(inputs, num_iteration=boosters['regression'].best_iteration)
        death = boosters['death'].predict(inputs, num_iteration=boosters['death'].best_iteration)
        predictions[split] = (np.asarray(mean, dtype=np.float32)[inverse], np.asarray(death, dtype=np.float32)[inverse])
    flat_history = [{'head': head, **{k: v for k, v in h.items() if k != 'curve'}} for head, h in history.items()]
    return predictions, {'heads': history, 'summary': flat_history}, {'best_iterations': {h: b.best_iteration for h, b in boosters.items()}}


def run(snapshot_dir, name, *, device='cuda:0', output=None, model_config=None, overrides=None, catalog=None, log=log_line):
    if name not in ALL_MODELS:
        raise ValueError(f'Unknown model {name}; choose from {ALL_MODELS}')
    catalog = catalog or load_catalog()
    hparams = load_model_config(model_config or ROOT / 'train/configs/models.json', name, overrides)
    if name in TORCH_MODELS and str(device).startswith('cuda') and hparams.get('gpu_memory_limit_gib'):
        total = torch.cuda.get_device_properties(device).total_memory
        fraction = float(hparams['gpu_memory_limit_gib']) * 2**30 / total
        if not 0 < fraction <= 1:
            raise ValueError('gpu_memory_limit_gib must be positive and fit the selected GPU')
        torch.cuda.set_per_process_memory_fraction(fraction, device)
    dataset = Dataset.load(snapshot_dir, catalog, log=log)
    summary = dataset.summary()
    log(json.dumps({'event': 'dataset', **summary}, ensure_ascii=False))
    if summary['train']['builds'] < hparams['min_train_builds']:
        raise ValueError('Insufficient distinct training builds; refusing to present a tiny smoke model as trained')
    snapshot_name = Path(snapshot_dir).name
    output = Path(output) if output else ROOT / 'checkpoints/train' / snapshot_name / name
    output.mkdir(parents=True, exist_ok=True)
    implementation = code_provenance()
    started = time.time()
    if name in TORCH_MODELS:
        predictions, history, extra = train_torch(name, dataset, hparams, device, output, log)
    else:
        predictions, history, extra = train_lightgbm(dataset, hparams, output, log)
    metrics = {}
    frames = []
    for split in SPLITS:
        rows = dataset.split_rows(split)
        mean, death = predictions[split]
        metrics[split] = evaluate(rows, mean, death)
        frame = rows[['job_id', 'source', 'kind', 'build_id', 'target_id', 'act_id', 'seed', 'max_hp', 'hp_loss', 'died', 'pair', 'weight']].copy()
        if 'execution_backend' in rows:
            frame['execution_backend'] = rows.execution_backend
        frame['split'] = split
        frame['pred_normalized'] = mean
        frame['pred_hp_loss'] = np.clip(mean, 0, 1) * frame.max_hp.to_numpy()
        frame['pred_death'] = death
        frames.append(frame)
        log(json.dumps({'event': 'metrics', 'split': split, 'summary': summarize(metrics[split])}))
    pd.concat(frames).to_parquet(output / 'predictions.parquet', index=False)
    vocab_json = canonical(dataset.vocab.spec)
    (output / 'vocab.json').write_text(vocab_json, encoding='utf-8')
    manifest = dataset.snapshot.manifest
    artifact = {'artifact_version': ARTIFACT_VERSION, 'model': name, 'kind': 'torch' if name in TORCH_MODELS else 'lightgbm',
                'input_kind': input_kind(name), 'hparams': hparams, 'created_at_utc': datetime.now(timezone.utc).isoformat(),
                'device': str(device), 'training_seconds': round(time.time() - started, 1), **extra,
                'snapshot': {'directory': str(snapshot_dir), 'snapshot_at_utc': manifest['snapshot_at_utc'], 'rows': manifest['rows'],
                             'builds': manifest['builds'], 'components': manifest['components'], 'files': manifest['files'],
                             'sources': [{k: s[k] for k in ('name', 'kind', 'db', 'rows')} for s in manifest['sources']]},
                'teachers': manifest['teachers'], 'teacher_signatures': manifest['teacher_signatures'],
                'allow_backend_mixture': manifest.get('allow_backend_mixture', False),
                'contains_experimental_results': manifest.get('contains_experimental_results', False),
                'code': implementation,
                'dataset': summary, 'label': {'normalized': 'hp_loss / max_hp', 'death': 'final_hp <= 0'},
                'vocab_sha256': hashlib.sha256(vocab_json.encode()).hexdigest(),
                'features': dataset.vocab.n_features, 'symbols': dataset.vocab.n_symbols,
                'trained_targets': sorted({f'{a}:{t}' for a, t in zip(dataset.pairs.act_id[dataset.pairs.split == 'train'],
                                                                     dataset.pairs.target_id[dataset.pairs.split == 'train'])}),
                'metrics_summary': {split: {k: metrics[split]['overall'][k] for k in ('pair_mae_hp', 'pair_rmse_hp', 'pair_r2', 'row_mae_hp', 'row_rmse_hp', 'death_brier', 'death_auc')} for split in SPLITS}}
    (output / 'artifact.json').write_text(json.dumps(artifact, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'training-builds.json').write_text(json.dumps({
        'train': sorted(dataset.pairs.build_id[dataset.pairs.split == 'train'].unique()),
        'validation': sorted(dataset.pairs.build_id[dataset.pairs.split == 'validation'].unique()),
        'groups': sorted(dataset.pairs.group[dataset.pairs.split != 'test'].unique())}), encoding='utf-8')
    (output / 'metrics.json').write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding='utf-8')
    (output / 'history.json').write_text(json.dumps(history, ensure_ascii=False), encoding='utf-8')
    log(json.dumps({'event': 'done', 'model': name, 'output': str(output), 'test': artifact['metrics_summary']['test']}))
    return output, metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--model', required=True, choices=ALL_MODELS)
    parser.add_argument('--device', default='cuda:0')
    parser.add_argument('--output')
    parser.add_argument('--model-config', default=str(ROOT / 'train/configs/models.json'))
    parser.add_argument('--set', nargs='*', default=[], help='Hyper-parameter overrides, e.g. epochs=5 lr=0.0005')
    args = parser.parse_args()
    overrides = {}
    for item in args.set:
        key, value = item.split('=', 1)
        overrides[key] = json.loads(value) if value[:1] in '0123456789-[{tfn"' else value
    run(args.snapshot, args.model, device=args.device, output=args.output, model_config=args.model_config, overrides=overrides)


if __name__ == '__main__':
    main()
