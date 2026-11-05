"""Inference: ``F(build, target, max_hp) -> normalized expected net HP loss``.

Usage::

    python -m train.predict --checkpoint checkpoints/train/<snap>/tabm \
        --build build.json --target BOWLBUGS_WEAK --max-hp 70
    # several checkpoints average their predictions (simple ensemble)
    python -m train.predict --checkpoint ck/tabm --checkpoint ck/lightgbm --builds-jsonl inputs.jsonl

Inputs are validated with the collection catalog first. Targets without
training coverage are rejected (as in ``damage_model.model.predict``). Legal
but untrained features/symbols are reported in ``untrained_features``; pass
``--strict`` to reject such extrapolation.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

import numpy as np
import scipy.sparse as sp
import torch

from damage_model.schema import Build

from .data import load_catalog
from .features import Vocabulary, pad_tokens


class Predictor:
    def __init__(self, directory, device='cpu'):
        self.directory = Path(directory)
        self.artifact = json.loads((self.directory / 'artifact.json').read_text(encoding='utf-8'))
        self.vocab = Vocabulary(json.loads((self.directory / 'vocab.json').read_text(encoding='utf-8')))
        self.name = self.artifact['model']
        self.device = torch.device(device)
        self.trained_targets = set(self.artifact['trained_targets'])
        if self.artifact['kind'] == 'torch':
            from .models import build_torch_model
            self.model = build_torch_model(self.name, self.vocab, self.artifact['hparams']).to(self.device)
            self.model.load_state_dict(torch.load(self.directory / 'weights.pt', map_location=self.device, weights_only=True))
            self.model.eval()
        else:
            import lightgbm as lgb
            self.boosters = {head: lgb.Booster(model_file=str(self.directory / f'{head}.lgb.txt')) for head in ('regression', 'death')}

    def encode(self, inputs):
        """``inputs``: list of ``(Build, target_id, max_hp)``. Returns model input plus untrained keys per item."""
        untrained = []
        if self.artifact['input_kind'] == 'sparse':
            rows, cols, vals = [], [], []
            for i, (build, target_id, max_hp) in enumerate(inputs):
                idx, val, missing = self.vocab.encode_sparse(build, target_id, max_hp)
                untrained.append(missing)
                rows.append(np.full(len(idx), i)); cols.append(idx); vals.append(val)
            matrix = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                                   shape=(len(inputs), self.vocab.n_features), dtype=np.float32)
            return matrix, untrained
        parts = []
        for build, target_id, max_hp in inputs:
            sym, num, missing = self.vocab.encode_tokens(build, target_id, max_hp)
            untrained.append(missing)
            parts.append((sym, num))
        symbols, numerics, _ = pad_tokens(parts)
        return (symbols.astype(np.int64), numerics), untrained

    @torch.no_grad()
    def predict_many(self, inputs, *, strict=False, batch_size=2048):
        for build, target_id, _ in inputs:
            if f'{build.act_id}:{target_id}' not in self.trained_targets:
                raise ValueError(f'Target has no training coverage: {build.act_id}:{target_id}')
        encoded, untrained = self.encode(inputs)
        if strict and any(untrained):
            raise ValueError('Input uses features absent from training: ' + json.dumps(sorted({k for m in untrained for k in m})))
        means, deaths = [], []
        if self.artifact['kind'] == 'lightgbm':
            means = self.boosters['regression'].predict(encoded)
            deaths = self.boosters['death'].predict(encoded)
        else:
            for start in range(0, len(inputs), batch_size):
                if self.artifact['input_kind'] == 'sparse':
                    dense = torch.from_numpy(encoded[start:start + batch_size].toarray()).to(self.device)
                    out = self.model(dense)
                else:
                    out = self.model(torch.from_numpy(encoded[0][start:start + batch_size]).to(self.device),
                                     torch.from_numpy(encoded[1][start:start + batch_size]).to(self.device))
                if out.ndim == 3:
                    means.append(out[..., 0].mean(dim=1).cpu()); deaths.append(torch.sigmoid(out[..., 1]).mean(dim=1).cpu())
                else:
                    means.append(out[:, 0].cpu()); deaths.append(torch.sigmoid(out[:, 1]).cpu())
            means, deaths = torch.cat(means).numpy(), torch.cat(deaths).numpy()
        results = []
        for (build, target_id, max_hp), mean, death, missing in zip(inputs, means, deaths, untrained):
            normalized = float(np.clip(mean, 0.0, 1.0))
            results.append({'model': self.name, 'normalized_expected_hp_loss': normalized,
                            'expected_hp_loss': normalized * float(max_hp), 'raw_normalized_prediction': float(mean),
                            'death_probability': float(np.clip(death, 0.0, 1.0)), 'untrained_features': sorted(set(missing))})
        return results

    def predict(self, build, target_id, max_hp, *, strict=False):
        return self.predict_many([(build, target_id, max_hp)], strict=strict)[0]

    @torch.no_grad()
    def predict_steps(self, step_inputs, *, batch_size=512):
        """Predict remaining combat HP loss and immediate-turn metrics from mid-combat live strings.

        ``step_inputs``: list of dicts or tuples ``(live_str, act_id, target_id, relics, max_hp)``.
        """
        from .step_snapshots import encode_live_step_tokens, STEP_IMM_TARGET_NAMES
        from .aux_labels import AUX_TARGET_NAMES
        parts = []
        max_hps = []
        for item in step_inputs:
            if isinstance(item, dict):
                live_str = item['live']
                act_id = item.get('act_id', 'OVERGROWTH')
                target_id = item.get('target', item.get('target_id', ''))
                relics = item.get('relics', [])
                max_hp = float(item.get('max_hp', 70))
            else:
                live_str, act_id, target_id, relics = item[0], item[1], item[2], item[3]
                max_hp = float(item[4] if len(item) > 4 else 70)
            enc = encode_live_step_tokens(live_str, act_id, target_id, relics, self.vocab.symbol_index)
            if enc is None:
                raise ValueError('Failed to parse live step string')
            parts.append(enc)
            max_hps.append(max_hp)
        symbols, numerics, _ = pad_tokens(parts)
        results = []
        for start in range(0, len(parts), batch_size):
            sym_t = torch.from_numpy(symbols[start:start + batch_size].astype(np.int64)).to(self.device)
            num_t = torch.from_numpy(numerics[start:start + batch_size]).to(self.device)
            out, aux, imm = self.model(sym_t, num_t, return_step=True)
            means = out[:, 0].cpu().numpy()
            deaths = torch.sigmoid(out[:, 1]).cpu().numpy()
            aux_np = aux.cpu().numpy() if aux is not None else None
            imm_np = imm.cpu().numpy() if imm is not None else None
            for i in range(len(means)):
                mhp = max_hps[start + i]
                norm_rem = float(np.clip(means[i], 0.0, 1.0))
                row = {
                    'model': self.name,
                    'normalized_expected_remaining_hp_loss': norm_rem,
                    'expected_remaining_hp_loss': norm_rem * mhp,
                    'raw_normalized_prediction': float(means[i]),
                    'death_probability': float(np.clip(deaths[i], 0.0, 1.0)),
                }
                if imm_np is not None:
                    row['step_immediate'] = {
                        name: float(imm_np[i, j]) for j, name in enumerate(STEP_IMM_TARGET_NAMES)
                    }
                    row['rem_hp_loss_per_turn_est'] = float(max(0.0, imm_np[i, 0]) * 10.0)
                    row['immediate_turn_damage_dealt_est'] = float(max(0.0, imm_np[i, 1]) * 20.0)
                    row['immediate_turn_block_gained_est'] = float(max(0.0, imm_np[i, 2]) * 20.0)
                    row['immediate_turn_hp_loss_est'] = float(max(0.0, imm_np[i, 3]) * 15.0)
                if aux_np is not None:
                    row['remaining_aux'] = {
                        name: float(aux_np[i, j]) for j, name in enumerate(AUX_TARGET_NAMES)
                    }
                results.append(row)
        return results

    def predict_step(self, live_str, act_id, target_id, relics, max_hp=70):
        return self.predict_steps([(live_str, act_id, target_id, relics, max_hp)])[0]


def ensemble(predictors, inputs, *, strict=False):
    """Average normalized predictions of several checkpoints (uniform weights)."""
    per_model = [p.predict_many(inputs, strict=strict) for p in predictors]
    out = []
    for i, (build, target_id, max_hp) in enumerate(inputs):
        members = [m[i] for m in per_model]
        normalized = float(np.mean([m['normalized_expected_hp_loss'] for m in members]))
        out.append({'model': 'ensemble', 'members': [m['model'] for m in members],
                    'normalized_expected_hp_loss': normalized, 'expected_hp_loss': normalized * float(max_hp),
                    'death_probability': float(np.mean([m['death_probability'] for m in members])),
                    'untrained_features': sorted({k for m in members for k in m['untrained_features']}),
                    'member_predictions': members})
    return out


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--checkpoint', action='append', required=True, help='Artifact directory; repeat to ensemble')
    parser.add_argument('--build', help='Build JSON file (damage_model.schema.Build.to_dict format)')
    parser.add_argument('--target', help='Encounter id')
    parser.add_argument('--max-hp', type=int, default=70)
    parser.add_argument('--builds-jsonl', help='Lines of {"build": {...}, "target": "...", "max_hp": 70}')
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--strict', action='store_true')
    parser.add_argument('--catalog'); parser.add_argument('--config')
    args = parser.parse_args()
    catalog = load_catalog(args.catalog, args.config)
    inputs = []
    if args.builds_jsonl:
        for line in Path(args.builds_jsonl).read_text(encoding='utf-8').splitlines():
            if line.strip():
                item = json.loads(line)
                inputs.append((Build.from_dict(item['build']), item['target'], item.get('max_hp', 70)))
    if args.build:
        inputs.append((Build.from_dict(json.loads(Path(args.build).read_text(encoding='utf-8'))), args.target, args.max_hp))
    if not inputs:
        parser.error('Provide --build/--target or --builds-jsonl')
    for build, _, _ in inputs:
        catalog.validate(build)
    predictors = [Predictor(path, args.device) for path in args.checkpoint]
    results = ensemble(predictors, inputs, strict=args.strict) if len(predictors) > 1 else predictors[0].predict_many(inputs, strict=args.strict)
    for result in results:
        sys.stdout.write(json.dumps(result, ensure_ascii=False) + '\n')


if __name__ == '__main__':
    main()
