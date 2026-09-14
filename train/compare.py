"""Train several models on one snapshot across the allowed GPUs and compare them.

Usage::

    python -m train.compare --snapshot data/train-snapshots/<stamp> --gpus 0,1 \
        --models repo_mlp rtdl_mlp rtdl_resnet tabm set_transformer lightgbm

Torch models are scheduled one at a time per GPU; LightGBM runs on the CPU in
parallel. Afterwards ``reports/<snapshot>/comparison.{md,json}`` summarise the
test metrics of every model plus a uniform ensemble of their test predictions.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import pandas as pd

from . import ROOT
from .metrics import evaluate
from .models import ALL_MODELS, TORCH_MODELS

COLUMNS = [('pair_mae_hp', 'pair MAE'), ('pair_rmse_hp', 'pair RMSE'), ('pair_r2', 'pair R²'),
           ('row_mae_hp', 'row MAE'), ('row_rmse_hp', 'row RMSE'), ('death_brier', 'death Brier'), ('death_auc', 'death AUC')]


def launch(snapshot, model, device, output, log_dir, overrides):
    log = (log_dir / f'{model}.log').open('w', encoding='utf-8')
    command = [sys.executable, '-m', 'train.train', '--snapshot', str(snapshot), '--model', model, '--device', device,
               '--output', str(output / model)]
    if overrides:
        command += ['--set', *overrides]
    process = subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT, cwd=ROOT)
    return {'model': model, 'device': device, 'process': process, 'log': log, 'started': time.time()}


def run_all(snapshot, models, gpus, output, log_dir, overrides=()):
    queue = [m for m in models if m in TORCH_MODELS]
    cpu_jobs = [m for m in models if m not in TORCH_MODELS]
    running, finished = [], {}
    free = list(gpus)
    for model in cpu_jobs:
        running.append(launch(snapshot, model, 'cpu', output, log_dir, overrides))
    while queue or running:
        while queue and free:
            running.append(launch(snapshot, queue.pop(0), f'cuda:{free.pop(0)}', output, log_dir, overrides))
        time.sleep(5)
        for job in list(running):
            code = job['process'].poll()
            if code is None:
                continue
            running.remove(job); job['log'].close()
            finished[job['model']] = {'exit_code': code, 'seconds': round(time.time() - job['started'], 1), 'device': job['device']}
            print(json.dumps({'event': 'finished', **finished[job['model']], 'model': job['model']}), flush=True)
            if job['device'].startswith('cuda:'):
                free.append(int(job['device'].split(':')[1]))
    return finished


def build_report(output: Path, models, runs, snapshot):
    rows, test_predictions = [], {}
    floors = None
    for model in models:
        artifact_path = output / model / 'artifact.json'
        if not artifact_path.exists():
            rows.append({'model': model, 'status': 'failed', **runs.get(model, {})})
            continue
        artifact = json.loads(artifact_path.read_text(encoding='utf-8'))
        metrics = json.loads((output / model / 'metrics.json').read_text(encoding='utf-8'))
        test = metrics['test']['overall']
        floors = floors or {k: v for k, v in test.items() if k.startswith('floor_')}
        rows.append({'model': model, 'status': 'ok', 'parameters': artifact.get('parameters'), 'best_epoch': artifact.get('best_epoch'),
                     'best_iterations': artifact.get('best_iterations'), 'training_seconds': artifact['training_seconds'],
                     'device': artifact['device'], 'features': artifact['features'], 'symbols': artifact['symbols'],
                     'validation': {k: metrics['validation']['overall'][k] for k, _ in COLUMNS},
                     'test': {k: test[k] for k, _ in COLUMNS},
                     'test_by_kind': {kind: {k: v[k] for k, _ in COLUMNS} for kind, v in metrics['test'].get('by_kind', {}).items()},
                     'test_by_act': {act: {k: v[k] for k, _ in COLUMNS} for act, v in metrics['test'].get('by_act_id', {}).items()}})
        frame = pd.read_parquet(output / model / 'predictions.parquet')
        test_predictions[model] = frame[frame.split == 'test'].set_index('job_id')
    ensemble = None
    if len(test_predictions) > 1:
        base = next(iter(test_predictions.values()))
        common = base.index
        for frame in test_predictions.values():
            common = common.intersection(frame.index)
        aligned = [f.loc[common] for f in test_predictions.values()]
        mean = np.mean([f.pred_normalized.to_numpy() for f in aligned], axis=0)
        death = np.mean([f.pred_death.to_numpy() for f in aligned], axis=0)
        frame = aligned[0].reset_index()
        frame['died'] = frame.died.astype(float)
        metrics = evaluate(frame, mean, death)
        ensemble = {'members': list(test_predictions), 'test': {k: metrics['overall'][k] for k, _ in COLUMNS},
                    'test_by_kind': {kind: {k: v[k] for k, _ in COLUMNS} for kind, v in metrics.get('by_kind', {}).items()}}
    report = {'generated_at_utc': datetime.now(timezone.utc).isoformat(), 'snapshot': str(snapshot), 'output': str(output),
              'models': rows, 'ensemble': ensemble, 'test_noise_floor': floors, 'runs': runs}
    return report


def fmt(value):
    if value is None:
        return '—'
    if isinstance(value, float):
        return f'{value:.4f}' if abs(value) < 1 else f'{value:.3f}'
    return str(value)


def markdown(report, manifest):
    lines = ['# 模型比较', '', f"快照：`{report['snapshot']}`（{manifest['snapshot_at_utc']}，{manifest['rows']} 场，{manifest['builds']} 个构筑，{manifest['components']} 个连通组）", '',
             '来源：' + '、'.join(f"{s['name']} {s['rows']} 场" for s in manifest['sources']), '',
             '划分（按源局连通组）：' + '；'.join(f"{k} {v['rows']} 场 / {v['pairs']} 对 / {v['builds']} 构筑 / {v['groups']} 组" for k, v in manifest['splits'].items()), '',
             '指标单位为 HP。pair 指标先对同一 (构筑, 目标) 的全部种子取均值再比较，row 指标按每场对战计算并以 1/种子数加权。', '']
    floors = report.get('test_noise_floor') or {}
    if floors:
        lines += ['测试集噪声下限：' + '，'.join(f"{k.replace('floor_', '')}={fmt(v)}" for k, v in floors.items()), '']
    header = '| 模型 | 参数量 | 训练秒数 | 最佳轮次 | ' + ' | '.join(f'测试 {label}' for _, label in COLUMNS) + ' | 验证 pair MAE |'
    lines += ['## 测试集（留出连通组）', '', header, '|' + '---|' * (header.count('|') - 1)]
    ok = [r for r in report['models'] if r['status'] == 'ok']
    for row in sorted(ok, key=lambda r: r['test']['pair_mae_hp']):
        best = row['best_epoch'] if row['best_epoch'] is not None else row['best_iterations']
        lines.append(f"| {row['model']} | {fmt(row['parameters'])} | {fmt(row['training_seconds'])} | {fmt(best)} | "
                     + ' | '.join(fmt(row['test'][k]) for k, _ in COLUMNS) + f" | {fmt(row['validation']['pair_mae_hp'])} |")
    if report.get('ensemble'):
        lines.append(f"| ensemble({len(report['ensemble']['members'])}) | — | — | — | " + ' | '.join(fmt(report['ensemble']['test'][k]) for k, _ in COLUMNS) + ' | — |')
    for row in report['models']:
        if row['status'] != 'ok':
            lines.append(f"| {row['model']} | 失败 (exit {row.get('exit_code')}) |" + ' — |' * (header.count('|') - 3))
    kinds = sorted({k for r in ok for k in r['test_by_kind']})
    if len(kinds) > 1:
        lines += ['', '## 按来源类型（测试集）', '', '| 模型 | 类型 | pair MAE | pair RMSE | pair R² | row MAE | death Brier |', '|---|---|---|---|---|---|---|']
        for row in sorted(ok, key=lambda r: r['test']['pair_mae_hp']):
            for kind in kinds:
                v = row['test_by_kind'].get(kind)
                if v:
                    lines.append(f"| {row['model']} | {kind} | {fmt(v['pair_mae_hp'])} | {fmt(v['pair_rmse_hp'])} | {fmt(v['pair_r2'])} | {fmt(v['row_mae_hp'])} | {fmt(v['death_brier'])} |")
    acts = sorted({a for r in ok for a in r['test_by_act']})
    if acts:
        lines += ['', '## 按幕（测试集 pair MAE）', '', '| 模型 | ' + ' | '.join(acts) + ' |', '|---|' + '---|' * len(acts)]
        for row in sorted(ok, key=lambda r: r['test']['pair_mae_hp']):
            lines.append(f"| {row['model']} | " + ' | '.join(fmt(row['test_by_act'].get(a, {}).get('pair_mae_hp')) for a in acts) + ' |')
    lines += ['', '## 说明', '',
              '- 各模型均为现有实现的适配：`repo_mlp` 为仓库 `damage_model.model.DamageNet`；`rtdl_mlp`/`rtdl_resnet` 来自 `rtdl_revisiting_models`；`tabm` 来自 `tabm`；`set_transformer` 为官方 Set Transformer 模块加 key padding mask；`lightgbm` 为两棵 LightGBM（回归 + 死亡二分类）。',
              '- 标签为 `净掉血 / 初始最大生命`，同一输入的重复种子按 1/种子数加权。早停依据验证集 pair MAE。',
              '- 噪声下限 `within_pair_rmse_hp` 为同输入多种子的组内标准差，是 row RMSE 的不可约部分；`loo_seed_mean_mae_hp` 是用同输入其他种子均值预测单场的 MAE，仅作参考，不是模型能达到的目标。',
              f"- 运行记录：{json.dumps(report['runs'], ensure_ascii=False)}"]
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--models', nargs='+', default=list(ALL_MODELS), choices=ALL_MODELS)
    parser.add_argument('--gpus', default='0,1', help='Comma separated GPU indices allowed for training')
    parser.add_argument('--output', help='Checkpoint root (default checkpoints/train/<snapshot>)')
    parser.add_argument('--report-dir', help='Default train/reports/<snapshot>')
    parser.add_argument('--set', nargs='*', default=[], help='Hyper-parameter overrides passed to every model')
    parser.add_argument('--report-only', action='store_true')
    args = parser.parse_args()
    snapshot = Path(args.snapshot)
    output = Path(args.output) if args.output else ROOT / 'checkpoints/train' / snapshot.name
    report_dir = Path(args.report_dir) if args.report_dir else ROOT / 'train/reports' / snapshot.name
    log_dir = ROOT / 'logs/train' / snapshot.name
    output.mkdir(parents=True, exist_ok=True); report_dir.mkdir(parents=True, exist_ok=True); log_dir.mkdir(parents=True, exist_ok=True)
    runs = {}
    if not args.report_only:
        gpus = [int(g) for g in args.gpus.split(',') if g.strip()]
        runs = run_all(snapshot, args.models, gpus, output, log_dir, args.set)
        (output / 'runs.json').write_text(json.dumps(runs, indent=2), encoding='utf-8')
    elif (output / 'runs.json').exists():
        runs = json.loads((output / 'runs.json').read_text(encoding='utf-8'))
    manifest = json.loads((snapshot / 'manifest.json').read_text(encoding='utf-8'))
    report = build_report(output, args.models, runs, snapshot)
    (report_dir / 'comparison.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    (report_dir / 'comparison.md').write_text(markdown(report, manifest), encoding='utf-8')
    print(markdown(report, manifest))


if __name__ == '__main__':
    main()
