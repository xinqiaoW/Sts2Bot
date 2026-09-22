# 实验比较（冻结快照 20260916-054432，测试划分未改）

快照与基线同一份：`data/train-snapshots/20260916-054432`。测试集仍是 82536 场 / 20638 对 / 368 个连通组。没有改 split、连通组或标签。

基线：已发布的 `set_transformer`（测试 pair MAE **4.002**）。

## 全部运行（按测试 pair MAE）

| 运行 | 做法 | 测试 pair MAE | RMSE | R² | death AUC | 验证 pair MAE | 最佳轮次 |
|---|---|---|---|---|---|---|---|
| **set_transformer_huber_pair** | 原架构 + Huber + pair 监督 | **3.927** | 6.386 | 0.8593 | 0.9826 | 4.141 | 52 |
| set_transformer_mae_pair | 原架构 + MAE + pair 监督 | 3.935 | 6.441 | 0.8569 | 0.9826 | 4.137 | 66 |
| set_transformer_baseline | 原 Set Transformer，逐场 MSE | 4.002 | 6.451 | 0.8565 | 0.9832 | 4.266 | 24 |
| set_transformer_wide_huber | d=256, 4 层 + Huber + pair | 4.018 | 6.616 | 0.8490 | 0.9815 | 4.204 | 35 |
| token_transformer | Pre-LN Transformer + Huber + pair | 4.054 | 6.692 | 0.8455 | 0.9799 | 4.278 | 68 |
| set_transformer_huber_row | 原架构 + Huber，仍逐场 | 4.054 | 6.714 | 0.8445 | 0.9817 | 4.330 | 29 |
| token_transformer_mse_row | Pre-LN Transformer，逐场 MSE | 5.046 | 7.909 | 0.7842 | 0.9763 | 5.187 | 5 |

## 最佳方案

**同一套 Set Transformer（35 万参数），把掉血头改成 Huber（δ=0.05），并按 (构筑, 目标) 对多种子标签取均值再训练**；`dropout=0.1`，`lr=0.00025`，`ReduceLROnPlateau`。

相对基线：测试 pair MAE 4.002 → **3.927**（−0.075 HP），pair RMSE 6.451 → 6.386，R² 0.8565 → 0.8593。死亡头几乎持平（AUC 0.9832 → 0.9826）。

测试子集（pair MAE）：

| | 基线 | Huber+pair |
|---|---|---|
| real | 3.671 | **3.589** |
| mutation | 5.040 | **4.983** |
| GLORY | 5.587 | 5.603 |
| HIVE | 4.273 | **4.196** |
| OVERGROWTH | 3.055 | **2.958** |
| UNDERDOCKS | 2.947 | **2.791** |

checkpoint：`checkpoints/train/20260916-exp/set_transformer_huber_pair/`

## 消融

- **Pair 监督是主因**：Huber 但仍逐场训练是 4.054，比基线更差；Huber+pair 才到 3.927。评估是 pair MAE，优化目标对齐后泛化更好。
- **Huber ≈ MAE**：MAE+pair 为 3.935，与 Huber+pair 几乎打平。两者都比 MSE 更贴近评估指标。
- **加宽/换骨架没有赢**：4 层 d=256 Set Transformer 测试 4.018（训练 2.49 vs 验证 4.20，过拟合）。Pre-LN token Transformer（376 万参数）4.054，训练集 2.01，同样过拟合。逐场 MSE 的 token Transformer 发散到 5.046。
- 结论：这个数据量级上，**损失与 pair 对齐的收益大于换更大/更现代的编码器**。

## GPU

最多占用两块空闲卡（实际用过 1 和 6）。没有动 4/5 上的 AIS 作业。测试连通组未改。
