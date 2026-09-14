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


class DeviceData:
    """Pair encodings and row labels resident on one device."""

    def __init__(self, dataset: Dataset, kind, device):
        self.device = torch.device(device)
        self.kind = kind
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
            self.indices = torch.from_numpy(indices).to(self.device)
            self.values = torch.from_numpy(values).to(self.device)
        else:
            self.symbols = torch.from_numpy(enc['symbols'].astype(np.int64)).to(self.device)
            self.numerics = torch.from_numpy(enc['numerics']).to(self.device)
        self.rows = {}
        for split in SPLITS:
            rows = dataset.split_rows(split)
            self.rows[split] = {k: torch.as_tensor(rows[c].to_numpy(), device=self.device)
                                for k, c in (('pair', 'pair'), ('y', 'y'), ('died', 'died'), ('weight', 'weight'))}
            self.rows[split]['pair'] = self.rows[split]['pair'].long()

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
    means, deaths = [], []
    for start in range(0, len(pairs), batch_size):
        out = forward(model, data, pairs[start:start + batch_size])
        if out.ndim == 3:
            out = torch.stack([out[..., 0].mean(dim=1), torch.sigmoid(out[..., 1]).mean(dim=1)], dim=-1)
        else:
            out = torch.stack([out[:, 0], torch.sigmoid(out[:, 1])], dim=-1)
        means.append(out[:, 0]); deaths.append(out[:, 1])
    return torch.cat(means).cpu().numpy(), torch.cat(deaths).cpu().numpy()


def train_torch(name, dataset, hparams, device, output, log):
    seed_everything(hparams['seed'])
    data = DeviceData(dataset, input_kind(name), device)
    model = build_torch_model(name, dataset.vocab, hparams).to(device)
    n_params = sum(p.numel() for p in model.parameters())
    log(json.dumps({'event': 'model', 'name': name, 'parameters': n_params, 'device': str(device)}))
    optimizer = torch.optim.AdamW(model.parameters(), lr=hparams['lr'], weight_decay=hparams['weight_decay'])
    train_rows = data.rows['train']
    n = len(train_rows['pair'])
    best, best_state, best_epoch, history = float('inf'), None, 0, []
    validation = dataset.split_rows('validation')
    started = time.time()
    for epoch in range(1, hparams['epochs'] + 1):
        model.train()
        order = torch.randperm(n, device=data.device)
        total, count = 0.0, 0
        for indices in order.split(hparams['batch_size']):
            out = forward(model, data, train_rows['pair'][indices])
            loss = loss_fn(out, train_rows['y'][indices], train_rows['died'][indices], train_rows['weight'][indices], hparams['death_loss_weight'])
            optimizer.zero_grad(set_to_none=True)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            optimizer.step()
            total += float(loss) * len(indices); count += len(indices)
        mean, death = predict_rows(model, data, 'validation')
        metrics = evaluate(validation, mean, death, groupers=())['overall']
        record = {'epoch': epoch, 'train_loss': total / count, 'validation_pair_mae_hp': metrics['pair_mae_hp'],
                  'validation_row_mae_hp': metrics['row_mae_hp'], 'validation_row_rmse_hp': metrics['row_rmse_hp'],
                  'validation_death_brier': metrics['death_brier'], 'elapsed_s': round(time.time() - started, 1)}
        history.append(record)
        log(json.dumps(record))
        if metrics['pair_mae_hp'] < best:
            best, best_epoch = metrics['pair_mae_hp'], epoch
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        elif epoch - best_epoch >= hparams['patience']:
            log(json.dumps({'event': 'early_stop', 'epoch': epoch, 'best_epoch': best_epoch}))
            break
    model.load_state_dict(best_state)
    torch.save(best_state, output / 'weights.pt')
    predictions = {split: predict_rows(model, data, split) for split in SPLITS}
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
        mean = boosters['regression'].predict(X[split], num_iteration=boosters['regression'].best_iteration)
        death = boosters['death'].predict(X[split], num_iteration=boosters['death'].best_iteration)
        predictions[split] = (np.asarray(mean, dtype=np.float32), np.asarray(death, dtype=np.float32))
    flat_history = [{'head': head, **{k: v for k, v in h.items() if k != 'curve'}} for head, h in history.items()]
    return predictions, {'heads': history, 'summary': flat_history}, {'best_iterations': {h: b.best_iteration for h, b in boosters.items()}}


def run(snapshot_dir, name, *, device='cuda:0', output=None, model_config=None, overrides=None, catalog=None, log=log_line):
    if name not in ALL_MODELS:
        raise ValueError(f'Unknown model {name}; choose from {ALL_MODELS}')
    catalog = catalog or load_catalog()
    hparams = load_model_config(model_config or ROOT / 'train/configs/models.json', name, overrides)
    dataset = Dataset.load(snapshot_dir, catalog, log=log)
    summary = dataset.summary()
    log(json.dumps({'event': 'dataset', **summary}, ensure_ascii=False))
    if summary['train']['builds'] < hparams['min_train_builds']:
        raise ValueError('Insufficient distinct training builds; refusing to present a tiny smoke model as trained')
    snapshot_name = Path(snapshot_dir).name
    output = Path(output) if output else ROOT / 'checkpoints/train' / snapshot_name / name
    output.mkdir(parents=True, exist_ok=True)
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
