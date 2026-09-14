# 训练 / 推理 / 验证

目标：`F(标准化卡组及逐张升级、附魔、持久状态, 遗物及采样计数, 原版怪物编组) → 标准化预期净掉血`，标签为 `净掉血 / 初始最大生命`（当前全部 70/70，即 `netHpLoss / 70`），另带死亡概率辅助头。

数据只读取 8 秒老师的有效标签：真实 `collection-real-runs-v3.sqlite`（协议 2，已封存）、`collection-real-runs-v4.sqlite`（协议 3，活动）、变异 `collection-mutations-v1.sqlite`（封存）、`collection-mutations-v2.sqlite`（活动）。来源列表在 [configs/sources.json](configs/sources.json)。训练不读活动库本身，只读一次性导出的冻结快照；不写回任何采集库，不写回采集输入或标签。

## 运行位置与准备条件

当前采集目录为 01 的 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot`。训练需要独立环境、可用 GPU 和完整冻结来源，不与持续采集控制器绑定。

迁移后核对发现：`/data1` 只有两个活动数据库，默认来源列表中的封存真实 v3 / 变异 v1 尚未迁入，`data/train-snapshots` 也未就绪；`.venv-train/bin/python` 仍指向旧 `/data2` 的解释器。**不能把现存 venv 路径或默认快照命令视为已经可用。** 先在健康存储上准备训练环境，补齐并核验冻结来源缓存，再执行下述流程。现有 `checkpoints/train/20260913-121204` 已在新盘；报告中的旧路径仍保留原始出处。

训练环境使用 `python -m venv --system-site-packages`，在包含 PyTorch 的基础环境中安装 `lightgbm`、`rtdl_revisiting_models`、`tabm`、`pyarrow` 等训练依赖。仓库尚无独立的训练依赖锁定文件，重建环境需核对实际包版本。不向采集环境安装训练依赖。Torch 模型可选 GPU，LightGBM 的训练实现使用 CPU；默认 `--gpus 0,1` 是工具参数，不代表这些 GPU 当前空闲。

默认 [configs/sources.json](configs/sources.json) 按 real-v4、real-v3、mut-v2、mut-v1 顺序去重。可将既有已核验快照的 `sources/` 缓存准备到健康路径，用 `--reuse` 复用 frozen 来源；每个来源需齐备 `.battles.parquet`、`.builds.json.gz`、`.edges.json.gz`、`.meta.json`。缺少缓存时工具会尝试读取配置中的数据库，不能靠 `--reuse` 绕过缺失数据。

若明确只训练活动来源，另建显式 `--config`，保留教师兼容键与划分设置，并在报告中注明覆盖变化。`--only` 仅导出指定来源缓存，跳过合并，不能把其输出当成完整训练快照。不要通过跳过卡牌验证或忽略教师不匹配来凑齐数据。

## 流程

以下示例中的 `<stamp>`、`<上次>` 等需替换为已准备的实际目录。

```bash
cd /data1/pl/ImageTask/wxq/Projects/Sts2Bot

# 1. 导出一致快照（每库一次只读事务；封存库可复用上一次快照的导出）
.venv-train/bin/python -m train.snapshot --reuse data/train-snapshots/<上次>
# → data/train-snapshots/<UTC 时间戳>/{battles.parquet, builds.json.gz, targets.json, manifest.json, sources/}

# 2. 训练单个模型
.venv-train/bin/python -m train.train --snapshot data/train-snapshots/<stamp> --model tabm --device cuda:0

# 3. 多模型比较（torch 模型按 GPU 轮转，LightGBM 在 CPU 并行）
.venv-train/bin/python -m train.compare --snapshot data/train-snapshots/<stamp> --gpus 0,1
# → checkpoints/train/<stamp>/<model>/，train/reports/<stamp>/comparison.{md,json}

# 4. 推理（单个或多个 checkpoint 均值集成）
.venv-train/bin/python -m train.predict --checkpoint checkpoints/train/<stamp>/tabm \
    --build build.json --target BOWLBUGS_WEAK --max-hp 70
.venv-train/bin/python -m train.predict --checkpoint ck/tabm --checkpoint ck/lightgbm --builds-jsonl inputs.jsonl

# 5. 用更新的快照验证旧 checkpoint（自动排除训练/验证过的构筑及其连通组）
.venv-train/bin/python -m train.evaluate --snapshot data/train-snapshots/<newer> --checkpoint checkpoints/train/<stamp>/tabm

# 6. 具体样例与误差分析（读各模型的 predictions.parquet，不重新推理）
.venv-train/bin/python -m train.inspect --snapshot data/train-snapshots/<stamp> --checkpoints checkpoints/train/<stamp> --primary set_transformer
# → train/reports/<stamp>/examples-test.md（校准表、编组内区分能力 vs “编组均值”基线、按编组/幕/牌数误差、最差高估/低估、模型分歧、随机样例）
#   默认 --split test：样例全部来自留出的测试连通组，训练/验证集里没有这些构筑及其变异亲属

# 测试
.venv-train/bin/python -m pytest tests/test_train_pipeline.py -q
```

## 快照与划分

快照逐库取得一致的只读视图；四个库并非同一原子时间点，分别记录导出时间。模型训练仅读取冻结结果。`train.evaluate` 默认排除 checkpoint 已见构筑及连通组；`--all-rows` 不再是独立留出评估，须另行标记。

- 每条记录必须是 `status='complete'`、`Passed`、`combatEnded`、观察 `complete`，并重新通过 `validate_hp` 与逐张 `validate_cards`；导出即失败于任何不一致。
- 同一 `(build, target, seed)` 出现在多个库时只保留 `sources.json` 顺序靠前者（v4 优先于 v3），去重数量写入 `manifest.json`。
- 老师兼容性：各库老师在 `teacher_compatibility_keys`（求解器、游戏 SHA、8000 ms、Medium、DOP 1 等）上必须一致；协议 2/3 的采集器摘要不同但搜索预算相同，允许并入并在 artifact 中保留全部老师。
- 划分按连通组：`build_origins`（构筑—源局）、`mutation_target_origins`（变异子—父源局）、`mutation_lineage`（子—父）做并查集，一个组只进一个集合（80/10/10，按组内源局哈希分桶，不保证场次数正好按该比例）。任何集合为空即拒绝训练。

## 特征

`train/features.py`：

- 稀疏视图：与 `damage_model.encoding.Encoder.encode` 完全一致的键与缩放（`tests/test_train_pipeline.py` 校验等价），只保留训练集中出现过的键；合法但未见过的键在推理时以 `untrained_features` 报告，非法键直接拒绝。供 `repo_mlp`、`rtdl_*`、`tabm`、`lightgbm` 使用。
- token 视图：每张牌一个 token（牌 ID、升级、附魔 ID、持久状态符号 + 附魔数值），每件遗物一个 token（遗物 ID、计数符号 + 顺序），目标与全局各一个 token。供 `set_transformer` 使用。

## 模型（均为现有实现的适配）

| 名称 | 来源 | 适配 |
|---|---|---|
| `repo_mlp` | 仓库 `damage_model.model.DamageNet` | 同结构，接入统一训练循环 |
| `rtdl_mlp` / `rtdl_resnet` | `rtdl_revisiting_models`（Gorishniy 等，NeurIPS 2021） | `d_in` = 词表大小，`d_out=2` |
| `tabm` | `tabm`（Gorishniy 等，ICLR 2025） | k=32 成员各自计算损失，预测取均值 |
| `set_transformer` | 官方 Set Transformer `modules.py`（Lee 等，ICML 2019） | 加 key padding mask 以批处理变长牌组 |
| `lightgbm` | LightGBM | 回归 + 死亡二分类两棵 booster，直接吃 CSR |

超参数见 [configs/models.json](configs/models.json)，可用 `--set key=value` 覆盖。损失 `MSE(标准化掉血) + 0.1·BCE(死亡)`，同一输入的重复种子按 `1/种子数` 加权（与仓库训练一致），早停看验证集 pair MAE。

## 指标

- `row_*`：逐场对战误差（包含战斗种子带来的波动），单位 HP。
- `pair_*`：先对同一 (构筑, 目标) 的所有种子取均值再比较，是评估“预期掉血”的主要指标；`pair_r2` 为对 pair 均值的解释比例。
- 组内波动参考：`within_pair_rmse_hp` 是有限种子样本的组内波动，`loo_seed_mean_mae_hp` 用同输入其他种子均值预测单场。它们不是已知总体分布的不可约误差下限；四种子均值本身也有采样误差。
- 死亡头：Brier 与 AUC。全部指标另按来源类型（real/mutation）、幕、来源库分组。

报告生成器目前仍使用历史名称“噪声下限”和 `test_noise_floor` 字段；其统计含义以上述解释为准。本次只纠正文档与现存报告的措辞，未修改统计计算或报告生成代码。

## 已有固定快照报告

| 快照 | 有效场次 / 构筑 / 连通组 | 比较与样例 |
| --- | --- | --- |
| 20260911-065245 | 552,043 / 54,748 / 1,413 | [模型比较](reports/20260911-065245/comparison.md)、[测试样例](reports/20260911-065245/examples-test.md) |
| 20260913-121204 | 770,682 / 77,039 / 2,071 | [模型比较](reports/20260913-121204/comparison.md)、[测试样例](reports/20260913-121204/examples-test.md) |

两份报告的测试连通组与数据分布不同，不能直接用跨报告 MAE 升降判断模型退步或进步。原指标、训练设置、耗时与快照路径保留作复现依据，不表示当前采集总量。比较优化效果应在同一固定留出集上评估。

## 产物

`checkpoints/train/<stamp>/<model>/`：`artifact.json`（模型、超参、快照文件摘要、老师、覆盖目标、指标摘要）、`vocab.json`、`weights.pt` 或 `*.lgb.txt`、`metrics.json`、`history.json`、`predictions.parquet`、`training-builds.json`。推理只依赖该目录与 `catalogs/`。

推理输出 `normalized_expected_hp_loss`（[0,1]）、`expected_hp_loss`（× max_hp）、`death_probability`、`untrained_features`；目标没有训练覆盖时拒绝，`--strict` 时任何未训练特征也拒绝。
