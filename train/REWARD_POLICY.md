# 战后奖励与卡牌决策搜索

CombatSolver 内奖励、商店及事件界面集成见 [Mod 说明](../docs/card-advisor.md)；完整策略与配置规则见 [配置说明](../docs/policy-configuration.md)。

入口为 `train.reward_policy.RewardSelector`，默认加载 `checkpoints/train/selected` 模型与 [configs/reward-policy.json](../configs/reward-policy.json)（默认值定义在 `train/policy_defaults.py`）。`RewardSelector.select` 既支持三张 `rewards` 输入，也支持通用 `options` 列表（`take` 携带 `card`，`remove` 携带 `deck_index`，`upgrade` 携带 `deck_index` 和升级后 `card`；末尾自动追加原牌组跳过/不操作基准）。

```bash
.venv-train/bin/python -m train.reward_policy \
  --input request.json \
  --output /tmp/reward-decision.json
```

使用 `--config my-policy.json` 覆盖参数，缺省字段继承 `REWARD_DEFAULTS`，未知字段报错。可传 `--checkpoint`、`--device`。`cpu_threads` 由 CLI 设置，嵌入应用时由调用方管理线程数。

## 输入

每次调用输入一个 JSON 对象，`build` 沿用 [SCORE.md](SCORE.md) 的完整构筑格式：

```python
request = {
    "build": current_build.to_dict(),
    "max_hp": 70,
    "budget_hp": 56,  # 可选，当前 HP，仅用于生存预算与权重判断，不作为模型输入
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
    "long_targets": {"VANTOM_BOSS": 1},  # 兼容旧字段名 boss_targets
    "long_target_room": "Boss",          # "Boss" 或 "Elite"
    "long_target_aggregation": "mean",   # "mean"，或双 Boss 时用 "max"
    "floors_to_boss": 8,
    # "encounter_act_id": "HIVE",        # 可选，当前幕或下一幕 ID（跨幕投影）
    # "terminal": False,                 # 可选，最终通关后无未来战斗时设为 True
    # "rollout_depth": 3,                # 可选，覆盖层数映射；0–6
    # "seed": 20261101,                  # 可选，覆盖配置中的随机种子
}
```

调用方负责从当前公开地图提供未来至多两层的可能遭遇与权重；每层敌人权重分别归一化，`combat_probability` 默认 1，休息/商店等非战斗层可填 `{"combat_probability": 0}`。`floors_to_boss` 是距本幕 Boss 的层数。奖励的升级、附魔与持久状态字段须按实际状态传入。

## 搜索和评分

1. 各候选操作分别生成构筑，末尾追加原牌组基准，形成独立根节点。
2. 在各根节点构筑上预测短期窗口掉血：每层先对敌人加权，再乘战斗概率与 `short_floor_weights`（默认 `[1.0, 1.0]`）。`short_reduction="mean"` 按有效战斗次数加权平均（非战斗层不作为 0 伤害战斗稀释均值），`"sum"` 取加权和，得到短期损失 $S$。
3. 长短期权重由未修改的原牌组基准统一决定：传入 `budget_hp` 时计算生存预算（扣除短期预期总战损与长期目标战损后是否严格高于安全余量），预算充足用 `short_weight / long_weight`（默认 `0.28 / 0.72`），不足用 `weak_short_weight / weak_long_weight`（默认 `0.72 / 0.28`）；未传 `budget_hp` 时回退到 `short_strength_loss_threshold` 兼容阈值。
4. 根据 `floors_to_boss`（或显式 `rollout_depth`）确定搜索深度 $n$。每个父节点独立有放回采样 `samples_per_parent`（默认 64）张牌、加上跳过，并在升级次数未达 `rollout_max_upgrades`（默认 1）时加入至多一条当前长期战损最低的牌组升级分支。
5. 将子节点构筑对长期目标评分（双 Boss `long_target_aggregation="max"` 时逐构筑取较难者）。前 `lookahead_pairs`（默认 1）对深度采用两步前瞻剪枝（先展开两层再按孙节点最优长期战损保留每个父节点的 `keep_per_parent` 条分支），其余深度单步保留 `keep_per_parent`（默认 6）个子节点。
6. 对每个根节点的末尾路径按长期战损升序排序，分别取最优前 `ceil(末尾数 × leaf_top_fraction)`（若设 `leaf_top_k` 则再取较小值）与较差后 `ceil(末尾数 × leaf_bottom_fraction)` 两组（默认各 25%），组内按排名 $r^{- \text{leaf\_rank\_power}}$ 归一化加权，再按 `leaf_top_weight : leaf_bottom_weight`（默认 `0.5 : 0.5`）混合得到长期损失 $L$。
7. 综合分数为 `-(w_short × S + w_long × L)`，分数越大越好。深度 0 时长期损失直接取根节点对长期目标的预测。

所有根节点在同深度、同父节点序号使用相同随机样本，降低候选间抽样方差。每次调用重置随机流。分支同分按跳过、采样牌、升级顺序稳定优先；根节点同分优先保留跳过（末尾基准）。

采样先按稀有度类别抽取（默认 Common:Uncommon:Rare = 9:5:1），再在该类别中均匀抽取卡牌 ID。卡池默认仅含静默猎手普通奖励牌（Common/Uncommon/Rare），不含基础牌、诅咒、事件牌或无色牌。严格模式只从训练已见的卡牌 ID 采样。

## 默认参数表（`REWARD_DEFAULTS`）

| 参数 | 默认值 | 含义 |
|---|---|---|
| `short_weight` / `long_weight` | `0.28` / `0.72` | 生存预算充足时的短/长期权重 |
| `weak_short_weight` / `weak_long_weight` | `0.72` / `0.28` | 生存预算不足时的短/长期权重 |
| `elite_safety_margin` / `boss_safety_margin` | `0.0` / `0.0` | 精英/Boss 生存预算安全余量 |
| `boss_target_after_act_floor` | `6` | 每幕该层之后长期目标固定面向 Boss |
| `short_strength_loss_threshold` / `elite_target_loss_threshold` | `10.0` / `20.0` | 无 `budget_hp` 旧输入的兼容阈值 |
| `short_floor_weights` | `[1.0, 1.0]` | 短期窗口两层的权重 |
| `short_reduction` | `"mean"` | `"mean"` 为按有效战斗次数加权平均；`"sum"` 为加权和 |
| `depth_schedule` | `≤2:0, ≤5:1, ≤8:2, ≤11:3, 其余:4` | 距 Boss 层数到基础 rollout 深度映射 |
| `post_boss_rollout_depth` | `3` | 非固定深度场景跨幕评估的 rollout 深度 |
| `samples_per_parent` | `64` | 每个父节点有放回采样张数（另加跳过与可选升级分支） |
| `keep_per_parent` | `6` | 每个父节点每层保留分支数 |
| `lookahead_pairs` | `1` | 两步前瞻剪枝的深度对数（`0–3`） |
| `rarity_weights` | `Common:9, Uncommon:5, Rare:1` | 稀有度类别采样权重 |
| `upgrade_probability` | `0.0` | 采样到的新牌直接为 +1 的概率 |
| `rollout_max_upgrades` | `1` | 每条 rollout 路径最多包含的已有卡牌升级次数（`0–6`） |
| `pool_card_ids` | `null` | 可选限制采样卡池的卡牌 ID 列表 |
| `leaf_top_fraction` / `leaf_bottom_fraction` | `0.25` / `0.25` | 末尾保留路径中参与聚合的最优/较差比例 |
| `leaf_top_weight` / `leaf_bottom_weight` | `0.5` / `0.5` | 最优尾与较差尾的混合权重 |
| `leaf_top_k` | `null` | 可选额外限制最优尾聚合数量 |
| `leaf_rank_power` | `1.0` | 尾部组内排名衰减幂次（`0` 为组内等权） |
| `seed` | `20261101` | 可复现采样种子 |
| `strict_features` | `true` | 独立评分默认拒绝训练未见特征（Bot 内固定覆盖为 `false`） |
| `inference_batch_size` | `128` | 每次模型批量推理的构筑数上限 |
| `cpu_threads` | `4` | CLI 的 Torch CPU 线程数 |

## Python 调用与边界

```python
from train.score import BuildScorer
from train.reward_policy import RewardSelector, load_config

selector = RewardSelector(BuildScorer(), load_config())
decision = selector.select(request)
index = decision["recommended_option_index"]
```

输出包含各候选的短期、初始长期、最优/较差尾及混合长期、综合分数，末尾路径、升级次数与聚合权重，排名、分差、权重依据和计算统计。`path` 中的 `null` 表示跳过，字典项表示升级分支或拿牌。

rollout 是受限的构筑潜力搜索，不是未来真实奖励的无偏期望：较差尾同样来自择优剪枝后的保留路径，升级分支未受真实篝火数量约束，也不模拟未来遗物、商店删牌、金币、药水或战后遗物触发。模型口径为 A10、70 满血、禁药水、8 秒求解；非 70 的 `max_hp` 会在 `warnings` 标记外推，超过模型牌组上限（45 张）或有效采样池为空时显式报错。
