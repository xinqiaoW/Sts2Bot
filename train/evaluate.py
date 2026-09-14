"""Evaluate trained artifacts on a snapshot, e.g. newer data collected after training.

Usage::

    python -m train.evaluate --snapshot data/train-snapshots/<newer> \
        --checkpoint checkpoints/train/<old>/tabm --checkpoint checkpoints/train/<old>/lightgbm

Rows whose build was used for training/validation of any checkpoint, or whose
connected group contains such a build, are excluded (``--holdout-only``,
default). With several checkpoints the uniform ensemble is evaluated as well.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from .data import Snapshot, load_catalog
from .metrics import evaluate, summarize
from .predict import Predictor


def holdout_rows(snapshot: Snapshot, checkpoints):
    seen_builds, seen_groups = set(), set()
    for path in checkpoints:
        record = json.loads((Path(path) / 'training-builds.json').read_text(encoding='utf-8'))
        seen_builds.update(record['train']); seen_builds.update(record['validation'])
    for build_id in seen_builds:
        if build_id in snapshot.builds:
            seen_groups.add(snapshot.builds[build_id]['group'])
    battles = snapshot.battles
    groups = battles.build_id.map(lambda b: snapshot.builds[b]['group'])
    mask = ~battles.build_id.isin(seen_builds) & ~groups.isin(seen_groups)
    return battles[mask].copy(), {'excluded_rows': int((~mask).sum()), 'excluded_builds': len(seen_builds)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--checkpoint', action='append', required=True)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--all-rows', action='store_true', help='Do not exclude rows connected to training builds')
    parser.add_argument('--output', help='Write metrics JSON here')
    args = parser.parse_args()
    snapshot = Snapshot(args.snapshot)
    catalog = load_catalog()
    if args.all_rows:
        rows, exclusion = snapshot.battles.copy(), {}
    else:
        rows, exclusion = holdout_rows(snapshot, args.checkpoint)
    if rows.empty:
        raise SystemExit('No held-out rows to evaluate')
    pair_keys = rows[['build_id', 'target_id']].drop_duplicates().reset_index(drop=True)
    pair_index = {(b, t): i for i, (b, t) in enumerate(zip(pair_keys.build_id, pair_keys.target_id))}
    rows['pair'] = [pair_index[(b, t)] for b, t in zip(rows.build_id, rows.target_id)]
    rows['weight'] = 1.0 / rows.groupby('pair').pair.transform('size')
    rows['died'] = rows.died.astype(float)
    max_hp = rows.groupby('pair').max_hp.first()
    inputs = [(snapshot.build(b), t, float(max_hp[i])) for i, (b, t) in enumerate(zip(pair_keys.build_id, pair_keys.target_id))]
    # Skip pairs whose target the model never saw; report them.
    report = {'snapshot': args.snapshot, 'rows': len(rows), 'pairs': len(inputs), **exclusion, 'models': {}}
    predictions = {}
    for path in args.checkpoint:
        predictor = Predictor(path, args.device)
        covered = np.array([f'{b.act_id}:{t}' in predictor.trained_targets for b, t, _ in inputs])
        subset = [inp for inp, ok in zip(inputs, covered) if ok]
        results = predictor.predict_many(subset)
        mean = np.full(len(inputs), np.nan); death = np.full(len(inputs), np.nan)
        mean[covered] = [r['raw_normalized_prediction'] for r in results]
        death[covered] = [r['death_probability'] for r in results]
        predictions[path] = (mean, death)
        row_mask = covered[rows.pair.to_numpy()]
        metrics = evaluate(rows[row_mask], mean[rows.pair.to_numpy()[row_mask]], death[rows.pair.to_numpy()[row_mask]])
        untrained = sum(len(r['untrained_features']) for r in results)
        report['models'][path] = {'model': predictor.name, 'uncovered_pairs': int((~covered).sum()),
                                  'inputs_with_untrained_features': int(sum(bool(r['untrained_features']) for r in results)),
                                  'untrained_feature_occurrences': untrained, 'metrics': metrics}
        print(json.dumps({'checkpoint': path, 'model': predictor.name, 'summary': summarize(metrics), 'uncovered_pairs': int((~covered).sum())}))
    if len(args.checkpoint) > 1:
        stack_mean = np.nanmean(np.stack([p[0] for p in predictions.values()]), axis=0)
        stack_death = np.nanmean(np.stack([p[1] for p in predictions.values()]), axis=0)
        covered = ~np.isnan(stack_mean)
        row_mask = covered[rows.pair.to_numpy()]
        metrics = evaluate(rows[row_mask], stack_mean[rows.pair.to_numpy()[row_mask]], stack_death[rows.pair.to_numpy()[row_mask]])
        report['models']['ensemble'] = {'model': 'ensemble', 'members': args.checkpoint, 'metrics': metrics}
        print(json.dumps({'checkpoint': 'ensemble', 'summary': summarize(metrics)}))
    if args.output:
        Path(args.output).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
