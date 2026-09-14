# 训练 / 推理 / 验证

目标：`F(真实卡组及升级及持久状态、逐张附魔, 遗物及采样计数, 原版怪物编组) → 标准化预期净掉血`，标签为 `净掉血 / 初始最大生命`（当前全部 70/70，即 `netHpLoss / 70`），另带死亡概率辅助头。

数据只读取 8 秒老师的有效标签：真实 `collection-real-runs-v3.sqlite`（协议 2，已封存）、`collection-real-runs-v4.sqlite`（协议 3，活动）、变异 `collection-mutations-v1.sqlite`（封存）、`collection-mutations-v2.sqlite`（活动）。来源列表在 [configs/sources.json](configs/sources.json)。训练不读活动库本身，只读一次性导出的冻结快照；不写回任何采集库，不改 `damage_model`。

环境：`.venv-train`（`python -m venv --system-site-packages`，在采集用 `.venv` 之上追加 `lightgbm`、`rtdl_revisiting_models`、`tabm`、`pyarrow`；不改动采集环境）。GPU 默认用 `cuda:0`、`cuda:1`，第三张仅临时占用时通过 `--gpus 0,1,2` 显式指定。

## 流程

```bash
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

- 每条记录必须是 `status='complete'`、`Passed`、`combatEnded`、观察 `complete`，并重新通过 `validate_hp` 与逐张 `validate_cards`；导出即失败于任何不一致。
- 同一 `(build, target, seed)` 出现在多个库时只保留 `sources.json` 顺序靠前者（v4 优先于 v3），去重数量写入 `manifest.json`。
- 老师兼容性：各库老师在 `teacher_compatibility_keys`（求解器、游戏 SHA、8000 ms、Medium、DOP 1 等）上必须一致；协议 2/3 的采集器摘要不同但搜索预算相同，允许并入并在 artifact 中保留全部老师。
- 划分按连通组：`build_origins`（构筑—源局）、`mutation_target_origins`（变异子—父源局）、`mutation_lineage`（子—父）做并查集，一个组只进一个集合（80/10/10，按组内源局哈希分桶）。任何集合为空即拒绝训练。

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

- `row_*`：逐场对战误差（含不可约的战斗随机性），单位 HP。
- `pair_*`：先对同一 (构筑, 目标) 的所有种子取均值再比较，是评估“预期掉血”的主要指标；`pair_r2` 为对 pair 均值的解释比例。
- 噪声下限：`within_pair_rmse_hp`（组内标准差，row RMSE 的下界）与 `loo_seed_mean_mae_hp`（用同输入其他种子均值预测单场，仅供参照）。
- 死亡头：Brier 与 AUC。全部指标另按来源类型（real/mutation）、幕、来源库分组。

## 首次比较（2026-09-11）

快照 `data/train-snapshots/20260911-065245`：552,043 场（real-v3 400,132、real-v4 91,180、mut-v1 60,731、mut-v2 当时为 0），54,748 个构筑，1,413 个连通组；测试集 41,954 场 / 10,490 对 / 134 组。完整表格见 [reports/20260911-065245/comparison.md](reports/20260911-065245/comparison.md)。

| 模型 | 测试 pair MAE (HP) | pair R² | row RMSE | death AUC |
|---|---|---|---|---|
| set_transformer | 4.26 | 0.813 | 9.95 | 0.976 |
| rtdl_resnet | 4.28 | 0.813 | 9.94 | 0.972 |
| tabm | 4.47 | 0.804 | 10.07 | 0.977 |
| repo_mlp | 4.67 | 0.783 | 10.34 | 0.972 |
| rtdl_mlp | 4.72 | 0.775 | 10.43 | 0.965 |
| lightgbm | 5.02 | 0.768 | 10.52 | 0.973 |
| 六模型均值集成 | 4.10 | 0.834 | 9.66 | 0.979 |

测试集噪声下限 `within_pair_rmse_hp = 8.07`，即 row RMSE 中约 8 HP 来自同输入的战斗随机性。变异构筑的误差高于真实构筑（pair MAE 5.2–5.9 对 4.1–4.9），第三幕（GLORY）最难。这些数字只对应该快照与 `configs/models.json` 的默认超参，未做超参搜索；数据继续扩充后应重新导出快照并重跑 `train.compare`。

## 产物

`checkpoints/train/<stamp>/<model>/`：`artifact.json`（模型、超参、快照文件摘要、老师、覆盖目标、指标摘要）、`vocab.json`、`weights.pt` 或 `*.lgb.txt`、`metrics.json`、`history.json`、`predictions.parquet`、`training-builds.json`。推理只依赖该目录与 `catalogs/`。

推理输出 `normalized_expected_hp_loss`（[0,1]）、`expected_hp_loss`（× max_hp）、`death_probability`、`untrained_features`；目标没有训练覆盖时拒绝，`--strict` 时任何未训练特征也拒绝。
