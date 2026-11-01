# 战后奖励选牌

CombatSolver 内奖励、商店及事件界面集成见 [Mod 说明](../docs/card-advisor.md)。`RewardSelector.select` 另支持 `options` 列表：`take` 携带 card，`remove` 携带 deck_index，`upgrade` 携带 deck_index 和升级后 card；末尾自动加原牌组基准。该接口保留原三张 rewards 输入的行为。

入口为 `train.reward_policy.RewardSelector`，默认模型仍是 `checkpoints/train/selected`。
集中参数文件：[configs/reward-policy.json](../configs/reward-policy.json)。

```bash
.venv-train/bin/python -m train.reward_policy \
  --input train/reports/20261101-reward-rollout/input.json \
  --output /tmp/reward-decision.json
```

使用 `--config my-policy.json` 覆盖参数，省略的顶层参数继承默认值；嵌套对象整体替换。
可传 `--checkpoint`、`--device`。`cpu_threads` 由 CLI 设置，嵌入应用时由宿主管理线程数。

## 输入

每次调用输入一个 JSON 对象，`build` 沿用 [SCORE.md](SCORE.md) 的完整构筑格式。

```python
request = {
    "build": current_build.to_dict(),
    "max_hp": 70,
    "rewards": [
        {"id": "FOOTWORK", "upgrade": 0},
        {"id": "BACKFLIP", "upgrade": 0},
        {"id": "DAGGER_SPRAY", "upgrade": 0},
    ],
    "next_floors": [
        {"targets": {"FLYCONID_NORMAL": 1, "NIBBITS_NORMAL": 1}},
        {"targets": {"BYGONE_EFFIGY_ELITE": 1, "PHROG_PARASITE_ELITE": 1},
         "combat_probability": 0.7},
    ],
    "boss_targets": {"VANTOM_BOSS": 1},
    "floors_to_boss": 8,
    # "rollout_depth": 2,  # 可选，覆盖层数映射；0–4
    # "seed": 20261101,   # 可选，覆盖配置中的随机种子
}
```

这里的奖励、近期遭遇和战斗概率是人为构造的演示，不是该牌组来源局的实际地图。
调用方负责从当前地图提供未来两层可能遭遇与权重；程序不会从历史来源窗口推断当前地图。
每层敌人权重分别归一化；`combat_probability` 默认 1，休息/商店等非战斗层可填 `{"combat_probability": 0}`。
临近 Boss 时可以只有一层，或空列表（短期分数为零）。Boss 未知时可提供同幕多个 Boss 的权重。
`floors_to_boss` 是调用方给定的距 Boss 层数，不等同于剩余战斗次数。奖励的升级、附魔等字段必须按实际状态传入。

## 搜索和评分

1. 三张牌各加入一张，外加跳过，形成四个独立根节点。
2. 在根节点的构筑上预测未来两层的掉血：每层先对敌人加权，再乘战斗概率；默认以 1.0、0.8 做层间加权平均，得到短期损失 S。
3. 根据距 Boss 层数确定 n。每个父节点独立有放回采样 32 张牌，加上跳过；默认全是未升级牌。
4. 将每个子节点的构筑直接对 Boss 评分，每个父节点各留掉血最少的 4 个，然后展开下一层。中间筛选只看 Boss 掉血。
5. 每个根最终有 `keep_per_parent ** n` 条末尾路径。不同路径可能得到相同牌组；路径保留，模型推理按牌组和敌人分布缓存。重复牌组也会重复参与路径加权。
6. 对末尾路径按 Boss 掉血升序排序，取最好的 `ceil(末尾数 × leaf_top_fraction)` 条；若设置 `leaf_top_k`，再取二者较小值，至少一条。排名 r 从 1 起，权重正比于 `r ** (-leaf_rank_power)`，归一化加权得到长期损失 L。
7. 综合分数为 `−(short_weight × S + long_weight × L) / (short_weight + long_weight)`，分数越大越好。深度 0 时长期分数直接取当前候选对 Boss 的预测。

所有根节点在同深度、同父节点排名使用相同随机样本，降低不同初始选项之间的抽样差异。
每次调用重置随机流，结果不受之前调用次数影响。分支同分优先保留跳过；根节点同分也优先跳过，其余按奖励位置。
采样先按稀有度类别抽取：金卡 Rare / 蓝卡 Uncommon / 白卡 Common 的权重为 1 / 5 / 9，即 6.67% / 33.33% / 60%；再在该类别中均匀抽一个卡牌 ID。类别概率不受该类卡牌总数影响。
这是有放回的独立采样，单批不保证恰好达到比例。同一父节点内可以重复抽到同一张牌，重复采样保留为独立分支，重复推理使用缓存；最佳四个分支也可能包含重复选牌。跳过额外加入，不参与稀有度抽样。
卡池默认仅含可用的静默猎手普通奖励牌（Common/Uncommon/Rare），不含基础牌、诅咒、事件牌或无色牌。若某类别因自定义池或严格特征筛选而为空，则只在剩余非空、正权重类别中重新归一化。
严格模式只从训练已见的卡牌 ID 采样，其他未见特征也由底层评分器拒绝。

## 参数表

| 参数 | 默认 | 含义 |
|---|---|---|
| `short_weight` / `long_weight` | 0.5 / 0.5 | 长短期综合权重 |
| `short_floor_weights` | [1, 0.8] | 下两层的权重 |
| `short_reduction` | mean | mean 为平均单层损失；sum 为加权和，但仍不是状态连续演化的路线损失 |
| `depth_schedule` | ≤2:0，≤5:1，≤8:2，≤11:3，其余4 | 距 Boss 层数到 rollout 深度；可用输入 rollout_depth 覆盖 |
| `samples_per_parent` | 32 | 每个父节点有放回采样次数，另加一次跳过 |
| `keep_per_parent` | 4 | 每个父节点保留数，改为 b 时末尾路径数是 b^n |
| `rarity_weights` | Common:9 / Uncommon:5 / Rare:1 | 稀有度类别概率权重；类内卡牌均匀，使用用户指定比例 |
| `upgrade_probability` | 0 | 每张采样牌成为 +1 的概率 |
| `pool_card_ids` | null | 可限制到指定奖励牌 ID 列表 |
| `leaf_top_fraction` | 0.25 | 末尾保留的最佳比例 |
| `leaf_top_k` | null | 可额外限制末尾聚合数量 |
| `leaf_rank_power` | 1 | 排名衰减力度；0 为选中末尾节点等权 |
| `seed` | 20261101 | 可复现的采样种子 |
| `strict_features` | true | 拒绝训练未见特征 |
| `inference_batch_size` | 128 | 每批构筑数量，限制推理内存 |
| `cpu_threads` | 4 | CLI 的 Torch CPU 线程数 |

## 接入机器人

```python
from train.score import BuildScorer
from train.reward_policy import RewardSelector, load_config

selector = RewardSelector(BuildScorer(), load_config())  # 启动时加载一次
decision = selector.select(request)
index = decision["recommended_option_index"]  # 0/1/2 为奖励位置，3 为跳过
```

输出包含四个候选的短期、初始 Boss、rollout 长期及综合分数；所有末尾路径、Boss 预测和聚合权重；最终排名、分差、有效配置、随机种子、实际卡池和计算量。
每条末尾路径中的 null 表示跳过。可从原构筑加初始奖励，再按 path 重建末尾构筑。
同一个 selector 可以重复调用；缓存仅在单次决策内有效。CLI 输出另含解析后的 checkpoint 路径。

这是乐观的构筑潜力搜索，不是未来真实奖励的无偏期望：每步从几十张中挑最优、末尾又取最好的一部分。
默认只模拟加牌和跳过，不模拟未来遗物、商店删牌、营火升级、金币、药水、战后遗物触发或当前血量变化。
模型仍是 A10、70 满血、禁药水、8 秒求解口径。非 70 的 max_hp 会标记外推；超过模型牌组上限或有效采样池为空时显式报错，不悄悄裁剪树。
模型误差会被搜索放大，尤其小分差不代表可靠提升；建议结合不同 seed、深度和权重观察选牌稳定性，再接实际战斗验证。

历史试跑结果见 [深度对照报告](reports/20261101-reward-rollout/report.md)，该报告使用修改前的等权卡牌 ID、不放回采样，不能作为当前概率配置的结果。
