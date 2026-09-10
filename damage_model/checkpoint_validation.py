"""Verify a saved model against its completed dataset and report simple baselines."""
import json
import math
from collections import defaultdict
from pathlib import Path

from .provenance import sha256
from .schema import Build, canonical, digest


def validate_checkpoint(store, catalog, output):
    import torch
    from .model import DamageNet, Encoder

    torch.set_num_threads(4)
    counts = store.counts()
    if set(counts) != {'complete'}:
        raise ValueError('Checkpoint validation requires a fully completed panel')
    rows = list(store.rows())
    output = Path(output)
    artifact = torch.load(output / 'model.pt', map_location='cpu', weights_only=True)
    saved = json.loads((output / 'metrics.json').read_text(encoding='utf-8'))
    if artifact['schema_version'] != 1 or artifact['label_scale'] != 70:
        raise ValueError('Unsupported checkpoint schema or HP scale')
    if {canonical(r['teacher']) for r in rows} != {canonical(artifact['teacher'])}:
        raise ValueError('Checkpoint teacher differs from dataset')
    if artifact['encoder'] != Encoder.from_catalog(catalog).spec:
        raise ValueError('Checkpoint encoder differs from catalog')
    splits = {s: [r for r in rows if r['split'] == s] for s in ('train', 'validation', 'test')}
    if artifact['training_build_ids'] != sorted({r['build_id'] for r in splits['train']}):
        raise ValueError('Checkpoint training builds differ from dataset')
    targets = sorted({r['build']['act_id'] + ':' + r['target']['id'] for r in splits['train']})
    if artifact['trained_targets'] != targets:
        raise ValueError('Checkpoint target coverage differs from dataset')
    if artifact['metrics'] != saved['metrics'] or not saved['history']:
        raise ValueError('Checkpoint and metrics file disagree')
    for entry in saved['history']:
        if not math.isfinite(entry['validation_mse_hp']):
            raise ValueError('Non-finite training history')
    if not all(torch.isfinite(v).all() for v in artifact['state_dict'].values()):
        raise ValueError('Non-finite model weights')
    encoder = Encoder(artifact['encoder'])
    model = DamageNet(len(encoder.positions), artifact['hidden'])
    model.load_state_dict(artifact['state_dict'])
    model.eval()
    groups = {}
    for split, records in splits.items():
        if not records:
            raise ValueError('Missing held-out split')
        groups[split] = defaultdict(list)
        for row in records:
            key = (row['build_id'], row['build']['act_id'], row['target']['id'])
            groups[split][key].append(row['result']['trainingObservation']['netHpLoss'])
        metrics = artifact['metrics'][split]
        expected = {'rows': len(records), 'builds': len({r['build_id'] for r in records}),
                    'families': len({r['build']['family'] for r in records}), 'pairs': len(groups[split])}
        if any(metrics[k] != v for k, v in expected.items()):
            raise ValueError('Checkpoint sample counts differ from dataset')
        for key in ('mae_hp', 'rmse_hp', 'pair_mean_mae_hp', 'pair_mean_rmse_hp', 'death_brier'):
            if not math.isfinite(metrics[key]) or metrics[key] < 0:
                raise ValueError('Invalid model metrics')
        if metrics['death_brier'] > 1:
            raise ValueError('Invalid death Brier score')
        row = records[0]
        vector = encoder.encode(Build.from_dict(row['build']), row['target']['id'],
                                row['result']['trainingObservation']['initialMaxHp'])
        with torch.no_grad():
            loss, death = model(torch.from_numpy(vector[None, :]))
        if not (torch.isfinite(loss).all() and torch.isfinite(death).all()):
            raise ValueError('Reloaded model produces non-finite predictions')

    # Fit baselines on training families only; score each build/target pair once.
    train_pairs = {k: sum(v) / len(v) for k, v in groups['train'].items()}
    global_mean = sum(train_pairs.values()) / len(train_pairs)
    by_target = defaultdict(list)
    for (_, act, target), value in train_pairs.items():
        by_target[(act, target)].append(value)
    target_mean = {k: sum(v) / len(v) for k, v in by_target.items()}
    baselines = {}
    for split in ('validation', 'test'):
        global_errors, target_errors = [], []
        uncovered = 0
        for (_, act, target), values in groups[split].items():
            observed = sum(values) / len(values)
            global_errors.append(abs(global_mean - observed))
            target_errors.append(abs(target_mean.get((act, target), global_mean) - observed))
            uncovered += (act, target) not in target_mean
        target_mae = sum(target_errors) / len(target_errors)
        baselines[split] = {'global_mean_pair_mae_hp': sum(global_errors) / len(global_errors),
                            'target_mean_pair_mae_hp': target_mae, 'uncovered_pairs': uncovered,
                            'model_improvement_over_target_mean_hp':
                                target_mae - artifact['metrics'][split]['pair_mean_mae_hp']}
    return {'validated': True, 'completed_samples': len(rows),
            'job_ids_sha256': digest(sorted(r['id'] for r in rows)),
            'model_sha256': sha256(output / 'model.pt'), 'checkpoint': str(output / 'model.pt'),
            'teacher': artifact['teacher'], 'metrics': artifact['metrics'], 'baselines': baselines,
            'note': 'Validation confirms artifact consistency; baseline comparisons measure usefulness, not optimal play.'}
