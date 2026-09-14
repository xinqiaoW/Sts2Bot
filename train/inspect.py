"""Concrete prediction examples and error breakdowns for trained checkpoints.

Usage::

    python -m train.inspect --snapshot data/train-snapshots/<stamp> \
        --checkpoints checkpoints/train/<stamp> --primary set_transformer

Reads the row-level ``predictions.parquet`` of every model directory under
``--checkpoints`` (no re-inference), aggregates them per (build, target) pair
and writes ``train/reports/<stamp>/examples.md`` with:

* calibration by predicted and by true HP loss, death calibration;
* error by encounter, by act, by deck/relic size, by source kind;
* the worst over/under-predictions, best pairs, largest model disagreements and
  random typical pairs, each listed with the full deck, relics, per-seed labels
  and every model's prediction.
"""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

import numpy as np
import pandas as pd

from . import ROOT
from .data import Snapshot

BINS = [0, 5, 10, 15, 20, 30, 40, 50, 60, 70.01]


def load_predictions(checkpoints: Path, split, models=None):
    frames = {}
    for directory in sorted(checkpoints.iterdir()):
        if not (directory / 'predictions.parquet').exists():
            continue
        if models and directory.name not in models:
            continue
        frame = pd.read_parquet(directory / 'predictions.parquet')
        frames[directory.name] = frame[frame.split == split].set_index('job_id')
    if not frames:
        raise SystemExit(f'No predictions under {checkpoints}')
    base = next(iter(frames.values()))[['source', 'kind', 'build_id', 'target_id', 'act_id', 'seed', 'max_hp', 'hp_loss', 'died', 'pair']].copy()
    for name, frame in frames.items():
        base[f'pred:{name}'] = frame.pred_hp_loss.reindex(base.index)
        base[f'death:{name}'] = frame.pred_death.reindex(base.index)
    names = list(frames)
    base['pred:ensemble'] = base[[f'pred:{n}' for n in names]].mean(axis=1)
    base['death:ensemble'] = base[[f'death:{n}' for n in names]].mean(axis=1)
    return base, names + ['ensemble']


def pair_table(rows, models):
    grouped = rows.groupby(['build_id', 'target_id'])
    pairs = grouped.agg(act_id=('act_id', 'first'), kind=('kind', 'first'), source=('source', 'first'), n=('hp_loss', 'size'),
                        true_mean=('hp_loss', 'mean'), true_std=('hp_loss', lambda s: float(s.std(ddof=1)) if len(s) > 1 else 0.0),
                        deaths=('died', 'sum'), max_hp=('max_hp', 'first'))
    pairs['labels'] = grouped.hp_loss.apply(list)
    for model in models:
        pairs[f'pred:{model}'] = grouped[f'pred:{model}'].first()
        pairs[f'death:{model}'] = grouped[f'death:{model}'].first()
        pairs[f'err:{model}'] = pairs[f'pred:{model}'] - pairs.true_mean
    return pairs.reset_index()


def fmt(v, digits=2):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return '—'
    return f'{v:.{digits}f}' if isinstance(v, (float, np.floating)) else str(v)


def table(headers, rows):
    out = ['| ' + ' | '.join(headers) + ' |', '|' + '---|' * len(headers)]
    out += ['| ' + ' | '.join(fmt(c) for c in row) + ' |' for row in rows]
    return out


def describe_cards(cards):
    counts = Counter()
    for card in cards:
        ench = f" [{card.get('enchantment_id')} {card.get('enchantment_amount')}]" if card.get('enchantment_id') else ''
        state = ' {' + ','.join(f'{k}={v}' for k, v in sorted(card.get('persistent_state', {}).items())) + '}' if card.get('persistent_state') else ''
        counts[f"{card['id']}{'+' + str(card['upgrade']) if card['upgrade'] else ''}{ench}{state}"] += 1
    return ', '.join(f'{k}×{n}' if n > 1 else k for k, n in sorted(counts.items()))


def describe_relics(relics):
    return ', '.join(r['id'] + ('(' + ','.join(f'{k}={v}' for k, v in r['state']) + ')' if r['state'] else '') for r in relics)


def example_block(pair, snapshot: Snapshot, models, targets):
    body = snapshot.builds[pair.build_id]['body']
    target = targets.get(pair.target_id, {})
    lines = [f"**{pair.act_id} / {pair.target_id}** ({target.get('room_type', '?')}{', weak' if target.get('weak') else ''}; 怪物 {', '.join(target.get('monsters', []))}) — {pair.kind} / {pair.source} / 构筑 `{pair.build_id[:12]}`",
             f"- 牌组 {len(body['cards'])} 张：{describe_cards(body['cards'])}",
             f"- 遗物 {len(body['relics'])} 件：{describe_relics(body['relics'])}"]
    lineage = snapshot.builds[pair.build_id].get('lineage')
    if lineage:
        lines.append(f"- 变异：{lineage['size']} / {lineage['axes']}，改牌 {lineage['cards_changed']} 改遗物 {lineage['relics_changed']}，父代 `{lineage['parent_id'][:12]}`")
    lines.append(f"- 标签（{pair.n} 个种子净掉血）：{pair.labels} → 均值 **{pair.true_mean:.1f}**，组内 std {pair.true_std:.1f}，死亡 {int(pair.deaths)}/{pair.n}")
    preds = ', '.join(f"{m} {pair[f'pred:{m}']:.1f} ({pair[f'err:{m}']:+.1f}, 死亡 {pair[f'death:{m}']:.2f})" for m in models)
    lines.append(f"- 预测（误差，死亡概率）：{preds}")
    return lines


def report(snapshot: Snapshot, rows, pairs, models, primary, n_examples, seed, train_pair_means):
    targets = snapshot.targets
    pairs['room'] = [targets.get(t, {}).get('room_type', '?') + ('(weak)' if targets.get(t, {}).get('weak') else '') for t in pairs.target_id]
    err, aerr = pairs[f'err:{primary}'], pairs[f'err:{primary}'].abs()
    targets = snapshot.targets
    lines = ['# 预测样例与误差分析', '',
             f"快照 `{snapshot.directory}`，测试集 {len(rows)} 场 / {len(pairs)} 对。主模型 **{primary}**（pair MAE {aerr.mean():.2f} HP，中位数 {aerr.median():.2f}，偏差 {err.mean():+.2f}）。"
             f"对比模型：{', '.join(models)}。误差 = 预测 − 同输入全部种子的均值，单位 HP。", '']
    # Error distribution and the noise of the pair-mean label itself
    q = aerr.quantile([0.25, 0.5, 0.75, 0.9, 0.95, 0.99])
    label_noise_mae = float((np.sqrt(2 / np.pi) * pairs.true_std / np.sqrt(pairs.n)).mean())
    lines += ['## 误差分布（主模型，pair 级）', '',
              *table(['分位', '25%', '50%', '75%', '90%', '95%', '99%'], [['|误差|'] + [fmt(v) for v in q]]),
              '', f"|误差| ≤ 2 HP 的 pair 占 {(aerr <= 2).mean():.1%}，≤ 5 HP 占 {(aerr <= 5).mean():.1%}，> 15 HP 占 {(aerr > 15).mean():.1%}。",
              '', f"注意“标签”本身是 4 个种子的均值，也带噪声：按组内 std/√n 估计，即使模型给出真实期望值，与 4 种子均值之间的 MAE 也约为 **{label_noise_mae:.2f} HP**（正态近似 √(2/π)·std/√n 的平均）。"
              f"因此主模型 pair MAE {aerr.mean():.2f} 中相当一部分来自标签噪声，而非模型误差。同理，“按标签均值分桶”中高标签桶的负偏差有一部分是选择效应（标签均值偶然偏高的 pair 被选进高桶），应以“按预测值分桶”判断校准。", '']
    # Calibration by predicted
    lines += ['## 校准：按预测值分桶', '', '每桶给出 pair 数、平均预测、平均标签均值、偏差、MAE。理想情况下平均预测 ≈ 平均标签。', '']
    pairs['_pb'] = pd.cut(pairs[f'pred:{primary}'], BINS, right=False)
    calib = pairs.groupby('_pb', observed=True).agg(n=('true_mean', 'size'), pred=(f'pred:{primary}', 'mean'), true=('true_mean', 'mean'), mae=(f'err:{primary}', lambda s: s.abs().mean()))
    lines += table(['预测区间', 'pairs', '平均预测', '平均标签', '偏差', 'MAE'], [[str(r.Index), r.n, r.pred, r.true, r.pred - r.true, r.mae] for r in calib.itertuples()])
    lines += ['', '## 校准：按标签均值分桶', '', '看模型在高掉血/死亡输入上是否系统性低估（向均值回归）。', '']
    pairs['_tb'] = pd.cut(pairs.true_mean, BINS, right=False)
    calib = pairs.groupby('_tb', observed=True).agg(n=('true_mean', 'size'), pred=(f'pred:{primary}', 'mean'), true=('true_mean', 'mean'), mae=(f'err:{primary}', lambda s: s.abs().mean()), wstd=('true_std', 'mean'))
    lines += table(['标签区间', 'pairs', '平均标签', '平均预测', '偏差', 'MAE', '组内 std'], [[str(r.Index), r.n, r.true, r.pred, r.pred - r.true, r.mae, r.wstd] for r in calib.itertuples()])
    # Death calibration
    lines += ['', '## 死亡概率校准（row 级）', '']
    rows['_db'] = pd.cut(rows[f'death:{primary}'], [0, 0.02, 0.05, 0.1, 0.2, 0.4, 0.6, 0.8, 1.01], right=False)
    dc = rows.groupby('_db', observed=True).agg(n=('died', 'size'), pred=(f'death:{primary}', 'mean'), rate=('died', 'mean'))
    lines += table(['预测死亡概率', 'rows', '平均预测', '实际死亡率'], [[str(r.Index), r.n, r.pred, r.rate] for r in dc.itertuples()])
    death_pairs = pairs[pairs.deaths > 0]
    lines += ['', f"含死亡的 pair {len(death_pairs)} 个（{len(death_pairs) / len(pairs):.1%}），其 pair MAE {death_pairs[f'err:{primary}'].abs().mean():.2f}，偏差 {death_pairs[f'err:{primary}'].mean():+.2f}；"
              f"无死亡 pair MAE {pairs[pairs.deaths == 0][f'err:{primary}'].abs().mean():.2f}。全部种子死亡的 pair {int((pairs.deaths == pairs.n).sum())} 个，平均预测 {pairs[pairs.deaths == pairs.n][f'pred:{primary}'].mean():.1f} HP。", '']
    # By encounter
    lines += ['## 按怪物编组（主模型，pair 级）', '', '按 MAE 从高到低；`弱` 为 weak 编组。', '']
    by_t = pairs.groupby(['act_id', 'target_id']).agg(n=('true_mean', 'size'), true=('true_mean', 'mean'), std=('true_std', 'mean'), bias=(f'err:{primary}', 'mean'), mae=(f'err:{primary}', lambda s: s.abs().mean()),
                                                     deaths=('deaths', 'sum'), rows=('n', 'sum')).reset_index()
    by_t['room'] = [targets.get(t, {}).get('room_type', '?') + ('弱' if targets.get(t, {}).get('weak') else '') for t in by_t.target_id]
    by_t = by_t.sort_values('mae', ascending=False)
    lines += table(['幕', '编组', '类型', 'pairs', '平均标签', '组内 std', '偏差', 'MAE', '死亡场/总场'],
                   [[r.act_id, r.target_id, r.room, r.n, r.true, r.std, r.bias, r.mae, f'{int(r.deaths)}/{int(r.rows)}'] for r in by_t.itertuples()])
    # Does the model just predict "this encounter is hard"? Compare with a per-encounter constant.
    lines += ['', '## 编组内区分能力：模型是否只在预测“这个怪难不难”', '',
              '基线 = 对每个编组恒定预测其**训练集**标签均值（只看怪、不看构筑）。若模型对同一编组的不同构筑预测几乎不变，其预测 std 会远小于标签 std，编组内相关系数接近 0，编组内 R² 也接近 0（R² = 1 − 模型 MSE / 基线 MSE，>0 表示比基线好）。', '']
    train_means = train_pair_means.groupby('target_id').true_mean.mean()
    baseline = pairs.target_id.map(train_means)
    base_err = baseline - pairs.true_mean
    within = []
    for target_id, g in pairs.groupby('target_id'):
        if len(g) < 5:
            continue
        pred, true = g[f'pred:{primary}'], g.true_mean
        mse_model = float(((pred - true) ** 2).mean()); mse_base = float(((baseline[g.index] - true) ** 2).mean())
        within.append({'act': g.act_id.iloc[0], 'target': target_id, 'room': targets.get(target_id, {}).get('room_type', '?') + ('弱' if targets.get(target_id, {}).get('weak') else ''),
                       'n': len(g), 'true_std': float(true.std()), 'pred_std': float(pred.std()),
                       'pearson': float(np.corrcoef(pred, true)[0, 1]) if pred.std() > 0 and true.std() > 0 else float('nan'),
                       'r2': 1 - mse_model / mse_base if mse_base > 0 else float('nan'),
                       'mae_model': float((pred - true).abs().mean()), 'mae_base': float((baseline[g.index] - true).abs().mean())})
    within = pd.DataFrame(within).sort_values('r2')
    lines += [f"整体：模型 pair MAE {aerr.mean():.2f}，编组均值基线 pair MAE {base_err.abs().mean():.2f}；基线 pair R² {1 - (base_err ** 2).mean() / ((pairs.true_mean - pairs.true_mean.mean()) ** 2).mean():.3f}，模型 pair R² {1 - (err ** 2).mean() / ((pairs.true_mean - pairs.true_mean.mean()) ** 2).mean():.3f}。"
              f"编组内相关系数中位数 {within.pearson.median():.2f}，编组内 R² 中位数 {within.r2.median():.2f}；模型在 {int((within.r2 > 0).sum())}/{len(within)} 个编组上优于基线，在 {int((within.r2 < 0.1).sum())} 个编组上几乎没有区分能力（R² < 0.1）。"
              f"模型预测 std / 标签 std 的中位数 {(within.pred_std / within.true_std).median():.2f}（接近 0 表示对该编组几乎恒定预测）。", '',
              '按编组内 R² 从低到高（最像“不分青红皂白”的排在前面）：', '']
    lines += table(['幕', '编组', '类型', 'pairs', '标签 std', '预测 std', '相关', '编组内 R²', 'MAE 模型', 'MAE 基线'],
                   [[r.act, r.target, r.room, r.n, r.true_std, r.pred_std, r.pearson, r.r2, r.mae_model, r.mae_base] for r in within.itertuples()])
    # Concrete illustration: for the hardest bosses, show the spread of predictions vs labels
    lines += ['', '各 Boss 编组内的预测分布（分位数），对照标签均值分布：', '']
    boss_rows = []
    for target_id, g in pairs[pairs.room.str.startswith('Boss')].groupby('target_id'):
        qp = g[f'pred:{primary}'].quantile([0.1, 0.5, 0.9]); qt = g.true_mean.quantile([0.1, 0.5, 0.9])
        boss_rows.append([g.act_id.iloc[0], target_id, len(g), f'{qt[0.1]:.0f} / {qt[0.5]:.0f} / {qt[0.9]:.0f}', f'{qp[0.1]:.0f} / {qp[0.5]:.0f} / {qp[0.9]:.0f}'])
    lines += table(['幕', 'Boss', 'pairs', '标签 10%/50%/90%', '预测 10%/50%/90%'], boss_rows)
    # By room type / act / kind
    lines += ['', '## 按房间类型、幕、来源类型', '']
    for column, title in (('room', '房间类型'), ('act_id', '幕'), ('kind', '来源类型')):
        g = pairs.groupby(column).agg(n=('true_mean', 'size'), true=('true_mean', 'mean'), bias=(f'err:{primary}', 'mean'), mae=(f'err:{primary}', lambda s: s.abs().mean()))
        lines += [f'### {title}', ''] + table([title, 'pairs', '平均标签', '偏差', 'MAE'] + [f'MAE {m}' for m in models if m != primary],
                                              [[r.Index, r.n, r.true, r.bias, r.mae] + [pairs[pairs[column] == r.Index][f'err:{m}'].abs().mean() for m in models if m != primary] for r in g.itertuples()]) + ['']
    # By deck size / relic count
    sizes = pairs.build_id.map(lambda b: len(snapshot.builds[b]['body']['cards']))
    relics = pairs.build_id.map(lambda b: len(snapshot.builds[b]['body']['relics']))
    pairs['_deck'] = pd.cut(sizes, [0, 12, 16, 20, 25, 30, 46], right=False)
    pairs['_relic'] = pd.cut(relics, [0, 3, 5, 8, 12, 40], right=False)
    for column, title in (('_deck', '牌组张数'), ('_relic', '遗物件数')):
        g = pairs.groupby(column, observed=True).agg(n=('true_mean', 'size'), true=('true_mean', 'mean'), bias=(f'err:{primary}', 'mean'), mae=(f'err:{primary}', lambda s: s.abs().mean()))
        lines += [f'### {title}', ''] + table([title, 'pairs', '平均标签', '偏差', 'MAE'], [[str(r.Index), r.n, r.true, r.bias, r.mae] for r in g.itertuples()]) + ['']
    # Model disagreement
    member_cols = [f'pred:{m}' for m in models if m != 'ensemble']
    pairs['_spread'] = pairs[member_cols].max(axis=1) - pairs[member_cols].min(axis=1)
    lines += ['## 模型分歧', '', f"各模型预测极差的中位数 {pairs._spread.median():.2f} HP，90% 分位 {pairs._spread.quantile(0.9):.2f}。分歧最大的 pair 与其真值：", '']
    for _, pair in pairs.sort_values('_spread', ascending=False).head(n_examples // 2).iterrows():
        lines += example_block(pair, snapshot, models, targets) + ['']
    # Examples
    def section(title, subset, note):
        out = [f'## {title}', '', note, '']
        for _, pair in subset.iterrows():
            out += example_block(pair, snapshot, models, targets) + ['']
        return out
    lines += section('最严重高估（预测 ≫ 标签）', pairs.sort_values(f'err:{primary}', ascending=False).head(n_examples), '模型认为会掉很多血，实际老师打得轻松。')
    lines += section('最严重低估（预测 ≪ 标签）', pairs.sort_values(f'err:{primary}').head(n_examples), '模型认为安全，实际老师掉血多或死亡。')
    hard_good = pairs[(pairs.true_mean >= 25) & (aerr <= 2)]
    lines += section('高掉血但预测准确', hard_good.sample(min(n_examples, len(hard_good)), random_state=seed) if len(hard_good) else hard_good, '标签均值 ≥ 25 HP 且 |误差| ≤ 2 HP 的 pair。')
    lines += section('随机典型样例', pairs.sample(min(n_examples, len(pairs)), random_state=seed), '无筛选随机抽取，反映一般水平。')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--checkpoints', required=True, help='Directory containing one sub-directory per trained model')
    parser.add_argument('--models', nargs='*', help='Subset of model directories to include')
    parser.add_argument('--primary', default='set_transformer')
    parser.add_argument('--split', default='test')
    parser.add_argument('--examples', type=int, default=8)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--output')
    args = parser.parse_args()
    snapshot = Snapshot(args.snapshot)
    rows, models = load_predictions(Path(args.checkpoints), args.split, args.models)
    if args.primary not in models:
        raise SystemExit(f'{args.primary} not among {models}')
    pairs = pair_table(rows, models)
    train_frame = pd.read_parquet(Path(args.checkpoints) / args.primary / 'predictions.parquet')
    train_frame = train_frame[train_frame.split == 'train']
    train_pair_means = train_frame.groupby(['build_id', 'target_id'], as_index=False).hp_loss.mean().rename(columns={'hp_loss': 'true_mean'})
    text = report(snapshot, rows, pairs, models, args.primary, args.examples, args.seed, train_pair_means)
    output = Path(args.output) if args.output else ROOT / 'train/reports' / Path(args.snapshot).name / f'examples-{args.split}.md'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding='utf-8')
    pairs.drop(columns=[c for c in pairs.columns if c.startswith('_')]).to_parquet(output.with_suffix('.pairs.parquet'), index=False)
    print(json.dumps({'output': str(output), 'pairs': len(pairs), 'models': models}))


if __name__ == '__main__':
    main()
