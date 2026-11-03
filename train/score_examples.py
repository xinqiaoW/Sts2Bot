"""Re-infer 48 stratified test examples and 12 controlled build edits."""
from __future__ import annotations

import argparse
from dataclasses import replace
import gzip
import json
from pathlib import Path

import numpy as np
import pandas as pd
import torch

from damage_model.schema import Build, Card
from .inspect import describe_cards, describe_relics
from .score import ASSUMPTIONS, BuildScorer, DEFAULT_CHECKPOINT


def selected_builds(path, wanted):
    """Stream the snapshot's JSON array without loading all 186k builds."""
    decoder = json.JSONDecoder()
    found, buffer = {}, ''
    with gzip.open(path, 'rt', encoding='utf-8') as stream:
        eof = False
        while not eof:
            chunk = stream.read(1024 * 1024)
            eof = not chunk
            buffer += chunk
            pos = 0
            while True:
                while pos < len(buffer) and buffer[pos] in ' \n\r\t[,':
                    pos += 1
                if pos == len(buffer) or buffer[pos] == ']':
                    break
                try:
                    record, end = decoder.raw_decode(buffer, pos)
                except json.JSONDecodeError:
                    if eof:
                        raise
                    break
                pos = end
                if record['id'] in wanted:
                    found[record['id']] = record
                    if len(found) == len(wanted):
                        return found
            buffer = buffer[pos:]
    raise ValueError(f'Missing snapshot builds: {wanted - found.keys()}')


def run(checkpoint, output, seed):
    output.mkdir(parents=True, exist_ok=True)
    torch.set_num_threads(4)
    scorer = BuildScorer(checkpoint)
    frame = pd.read_parquet(Path(checkpoint) / 'predictions.parquet', filters=[('split', '==', 'test')])
    pairs = frame.groupby(['act_id', 'build_id', 'target_id', 'max_hp'], sort=True).agg(
        actual=('hp_loss', 'mean'), std=('hp_loss', 'std'), n=('hp_loss', 'size'),
        observed_death=('died', 'mean'), saved_prediction=('pred_hp_loss', 'first'),
        labels=('hp_loss', list), kind=('kind', 'first')).reset_index()
    pairs['tier'] = pairs.target_id.map(lambda t: 'BOSS' if t.endswith('_BOSS') else 'ELITE' if t.endswith('_ELITE') else 'NORMAL/WEAK')
    # Fixed seed; no filtering by error or prediction, four per act/encounter tier.
    picked = pd.concat([g.sample(n=4, random_state=seed) for _, g in pairs.groupby(['act_id', 'tier'])], ignore_index=True)
    snapshot = Path(scorer.predictor.artifact['snapshot']['directory'])
    records = selected_builds(snapshot / 'builds.json.gz', set(picked.build_id))
    requests = []
    for i, row in picked.iterrows():
        record = records[row.build_id]
        assert record['split'] == 'test'
        requests.append(dict(id=f'E{i+1:02}', build=record['body'], target=row.target_id, max_hp=int(row.max_hp)))
    variants = []
    for act_id in sorted(picked.act_id.unique()):
        for base in requests:
            b = Build.from_dict(base['build'])
            candidates = [i for i, c in enumerate(b.cards) if c.id == 'STRIKE_SILENT' and c.upgrade == 0]
            if b.act_id != act_id or not candidates or len(b.cards) >= scorer.catalog.config['max_deck_size']:
                continue
            index = candidates[0]
            edits = [('删除一张未升级打击', b.cards[:index] + b.cards[index+1:]),
                     ('升级一张打击', b.cards[:index] + (replace(b.cards[index], upgrade=1),) + b.cards[index+1:]),
                     ('加入一张 FOOTWORK', b.cards + (Card('FOOTWORK'),))]
            for label, cards in edits:
                request = dict(base, id=f'V{len(variants)+1:02}', build=replace(b, cards=cards).to_dict())
                variants.append((base['id'], label, request))
            break
    all_requests = requests + [v[2] for v in variants]
    results = scorer.score_many(all_requests)
    by_id = {r['id']: r for r in results}
    loss = np.array([r['expected_hp_loss'] for r in results[:len(picked)]])
    errors = loss - picked.actual.to_numpy()
    summary = dict(checkpoint=str(Path(checkpoint).resolve()), seed=seed, test_examples=len(picked),
                   controlled_edits=len(variants), mae_hp=float(np.abs(errors).mean()),
                   rmse_hp=float(np.sqrt(np.mean(errors**2))), mean_error_hp=float(errors.mean()),
                   max_abs_error_hp=float(np.abs(errors).max()),
                   max_reload_difference_hp=float(np.abs(loss - picked.saved_prediction.to_numpy()).max()),
                   examples_with_untrained_features=sum(bool(r['untrained_features']) for r in results))
    for name, data in [('inputs.jsonl', all_requests), ('predictions.jsonl', results)]:
        (output / name).write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in data), encoding='utf-8')
    (output / 'summary.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    details = picked.copy()
    details.insert(0, 'id', [r['id'] for r in requests])
    details['prediction'] = loss
    details['error'] = errors
    details['death_prediction'] = [r['death_probability'] for r in results[:len(picked)]]
    details.to_csv(output / 'comparison.csv', index=False)
    lines = ['# 预期掉血试跑', '', f'模型：`{summary["checkpoint"]}`。', '',
             f'条件：{ASSUMPTIONS}。分数 = −预期掉血，越大越好。', '',
             f'固定随机种子 {seed}，从 test 划分按四个区域 × 普通/精英/Boss 各抽 4 对，共 48 对；未按预测或误差筛选。',
             '实际均值来自训练快照中已有的测试战斗记录，本次重新加载权重推理，未重新运行战斗模拟器。普通组包含弱敌。',
             '这些是同一模型数据中的留出样例，不代表新游戏版本或在线爬塔表现。实际均值也有有限种子噪声。', '',
             f'本次 MAE **{summary["mae_hp"]:.2f} HP**，RMSE **{summary["rmse_hp"]:.2f} HP**，平均偏差 **{summary["mean_error_hp"]:+.2f} HP**；完整测试集 pair MAE 为 4.15 HP。',
             f'重载推理与已存预测最大差 {summary["max_reload_difference_hp"]:.6f} HP；{summary["examples_with_untrained_features"]} 个输入包含训练未见特征（详见 predictions.jsonl）。', '',
             '| 编号 | 区域 | 遭遇 | 牌/遗物 | 预测掉血 | 实际均值 ± 标准差 | 误差 | 战斗数 | 满血死亡预测/实测 |',
             '|---|---|---|---|---:|---:|---:|---:|---:|']
    for i, row in details.iterrows():
        b = requests[i]['build']
        lines.append(f'| [{row.id}](#{row.id.lower()}) | {row.act_id} | {row.target_id} | {len(b["cards"])}/{len(b["relics"])} | {row.prediction:.2f} | {row.actual:.2f} ± {row["std"]:.2f} | {row.error:+.2f} | {row.n} | {row.death_prediction:.1%}/{row.observed_death:.1%} |')
    lines += ['', '## 构筑改动敏感性', '',
              '每个区域取一个含未升级打击的上述样例，只改一处，敌人和生命上限不变。以下没有改动后的实测标签；只检查模型响应，不能据此证明选牌收益。', '',
              '| 编号 | 原构筑 | 改动 | 原掉血 | 改后掉血 | 差值（负数为改善） |', '|---|---|---|---:|---:|---:|']
    for base, label, request in variants:
        before, after = by_id[base]['expected_hp_loss'], by_id[request['id']]['expected_hp_loss']
        lines.append(f'| {request["id"]} | {base} | {label} | {before:.2f} | {after:.2f} | {after-before:+.2f} |')
    lines += ['', '## 完整输入与实测掉血', '', '卡牌用游戏内部 ID 表示，+1 表示升级；遗物顺序及计数保留。JSONL 保留全部附魔、持久状态和古代事件历史。']
    for request, (_, row) in zip(requests, details.iterrows()):
        b = request['build']
        lines += ['', f'### {request["id"]}', '', f'区域：{b["act_id"]} / 第 {b["act"]} 幕；生命上限：{request["max_hp"]}；来源类型：{row.kind}。',
                  f'构筑 ID：`{row.build_id}`。', '', f'卡组：{describe_cards(b["cards"])}。', '',
                  f'遗物：{describe_relics(b["relics"])}。', '',
                  f'古代事件历史：`{json.dumps(b["ancient_history"], ensure_ascii=False)}`。', '',
                  f'对战 {row.target_id}：预测 {row.prediction:.2f} HP；各次实测：{row.labels}。']
    (output / 'report.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(summary, indent=2, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', default=str(DEFAULT_CHECKPOINT))
    parser.add_argument('--output', type=Path, default=Path('train/reports/20261101-score-examples'))
    parser.add_argument('--seed', type=int, default=20261101)
    args = parser.parse_args()
    run(args.checkpoint, args.output, args.seed)


if __name__ == '__main__':
    main()
