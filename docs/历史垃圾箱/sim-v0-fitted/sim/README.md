# 抽象整局模拟器 v0（归档设计）

以下保留退役实现的设计和原目录命令，用于解释固定实验报告；代码搬入归档后不能按这些命令直接运行。现行环境与归档边界见[上级说明](../README.md)。

不启动游戏，用 Python 模拟一整局（三幕）的**战斗外决策**，战斗结果交给可插拔的战斗预言机（默认是训练好的预期掉血模型 `F`，`train.predict`）。它曾用于探索低成本整局模拟，但不具备原版规则等价性。

## 数据来源与设计原则

游戏目录（`catalogs/game-0.111.0.raw.json`）只给出卡牌/遗物/遭遇的**集合**，不含生成权重。所有战斗外规则因此都从公开 Spire Codex `.run` 历史里**经验拟合**（`sim.tables`），这些拟合值不等同于原版生成规则：

- 8,030 局原版 Silent A10（`source_runs`，按 `run_hash` 去重，过滤模组幕/多人）；按哈希 80/20 分成 **拟合集**（6,401）和 **留出集**（1,629）。表只用拟合集，偏差报告只对留出集比较。
- 拟合内容：第一幕选择、每层节点类型分布、`?` 房解析、每幕遭遇池与 `_WEAK` 前缀长度、各房间金币、卡牌奖励稀有度、商店库存/价格/删牌价、精英/宝箱遗物稀有度、事件频率与事件结果（ΔHP/Δ金币/得失卡/遗物）、上古选择与遗物提供、遗物拾取时的即时效果（如草莓 +7 上限）。
- 从历史里**核对**而非拟合的结构常量（`sim.tables.STRUCTURE`）：起始 56/70 HP、99 金币；每幕层数（15/14/13 + boss）；宝箱层；篝火治疗 30 %；进入第二/三幕时回复 `floor(0.8 × 已损 HP)`；Boss 75 金币；删牌 100 起每次 +50。

## 模块

| 文件 | 作用 |
|---|---|
| `history.py` | 只读加载 `.run`，展平成逐层记录（人类与模拟共用同一格式），拟合/留出切分 |
| `tables.py` | 拟合经验表 → `data/sim/tables-v0.json`（`python -m sim.tables`） |
| `map.py` | 幕地图生成（7 列随机上行路径；行类型用人类**到访**分布作权重，固定行结构） |
| `env.py` | `RunEnv`：阶段 `ancient / map / card_reward / rest / shop / combat`，动作为元组；`VecRunEnv` 批量解析战斗 |
| `oracle.py` | `ModelOracle`（`F` 集成，可选悲观项 `mean + λ·std`、噪声、死亡头）与 `EmpiricalOracle`（人类掉血直方图，忽略卡组，仅作参照） |
| `policies.py` | `RandomPolicy`、`HeuristicPolicy`（规则基线）、`GreedyFPolicy`（卡牌/升级/上古用 `F` 一步前瞻） |
| `rollout.py` | 批量 rollout，输出与人类相同格式的逐层记录 |
| `calibrate.py` | 逐层校准：人类留出集 vs 各模拟臂，写 `reports/sim/<stamp>/deviation.{md,json}` |

## 用法

```bash
# 1. 拟合表（需要 data/collection-real-runs-v4.sqlite，只读；结果缓存到 data/sim/）
.venv/bin/python -m sim.tables

# 2. 校准 + 偏差报告（F 需要 .venv-train；不给 --checkpoint 则只跑经验预言机臂）
C=checkpoints/train/20260911-065245
.venv-train/bin/python -m sim.calibrate --episodes 2000 --greedy-episodes 500 --human-build-runs 400 --device cuda:0 \
    --checkpoint $C/set_transformer --checkpoint $C/rtdl_resnet --checkpoint $C/tabm \
    --checkpoint $C/rtdl_mlp --checkpoint $C/repo_mlp --checkpoint $C/lightgbm \
    --snapshot data/train-snapshots/20260911-065245

# 3. 测试
.venv-train/bin/python -m pytest tests/test_sim.py -q
```

编程接口：

```python
from train.data import load_catalog
from sim.tables import load_tables
from sim.env import RunEnv
from sim.oracle import ModelOracle

env = RunEnv(load_tables(), load_catalog(), ModelOracle([...checkpoints...], device='cuda:0'), seed=0)
obs = env.observation()
while not env.done:
    obs, reward, done, info = env.step(env.legal_actions()[0])   # reward = 1 仅在通关时
```

## 报告怎么读

`reports/sim/<stamp>/deviation.md` 各节：1 局结果（胜率、到达层数、死亡幕/房间）；2 逐层轨迹（HP 比、上限、金币、卡组、遗物数）；3 地图结构（每幕每层到访类型 TV 距离）；4 遭遇池；5 奖励；6 篝火/商店/事件；7 各遭遇掉血（人类 vs 各臂 vs `F` 均值 vs 老师标签）；8 **`F` 在真实人类构筑上的偏差**（把留出局的每场战斗用当时的真实卡组重新打分，区分"预言机偏差"和"卡组质量"）；9 v0 未建模清单。

臂：`sim/empirical/*` 检验战斗外规则本身（掉血按人类直方图抽样）；`sim/F/heuristic` 与 `sim/F/greedy_f` 检验 `F` 作为预言机时整局的行为。

## v0 已知缺口

药水完全忽略；地图只能校准到访分布；事件结果不随当前状态条件化、也不会致死；遗物只建模拾取时的即时数值效果；篝火只有治疗/升级；卡牌奖励固定 3 张 Silent 池；基线策略不复现人类决策质量。详见报告第 9 节。
