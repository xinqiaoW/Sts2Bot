# 模型比较

> 本报告保留该固定快照的原指标与样例，路径是生成时的出处，不是当前采集工作目录。现行环境与指标解释见[训练说明](../../README.md)；不同快照的留出集不能直接作同条件比较。

快照：`data/train-snapshots/20260911-065245`（2026-09-11T06:53:24.979422+00:00，552043 场，54748 个构筑，1413 个连通组）

来源：real-v4 91180 场、real-v3 400132 场、mut-v2 0 场、mut-v1 60731 场

划分（按源局连通组）：train 459024 场 / 114778 对 / 45498 构筑 / 1156 组；validation 51065 场 / 12769 对 / 5045 构筑 / 123 组；test 41954 场 / 10490 对 / 4205 构筑 / 134 组

指标单位为 HP。pair 指标先对同一 (构筑, 目标) 的全部种子取均值再比较，row 指标按每场对战计算并以 1/种子数加权。

测试集组内波动参考：within_pair_rmse_hp=8.074，loo_seed_mean_mae_hp=5.817，multi_seed_rows=41954，pairs_with_multiple_seeds=10490

## 测试集（留出连通组）

| 模型 | 参数量 | 训练秒数 | 最佳轮次 | 测试 pair MAE | 测试 pair RMSE | 测试 pair R² | 测试 row MAE | 测试 row RMSE | 测试 death Brier | 测试 death AUC | 验证 pair MAE |
|---|---|---|---|---|---|---|---|---|---|---|---|
| set_transformer | 352514 | 612.400 | 29 | 4.256 | 7.072 | 0.8127 | 6.236 | 9.945 | 0.0198 | 0.9762 | 4.329 |
| rtdl_resnet | 1652994 | 528.600 | 41 | 4.284 | 7.059 | 0.8133 | 6.308 | 9.936 | 0.0200 | 0.9715 | 4.398 |
| tabm | 2518752 | 619.400 | 40 | 4.472 | 7.239 | 0.8037 | 6.488 | 10.065 | 0.0199 | 0.9766 | 4.430 |
| repo_mlp | 447618 | 328.100 | 6 | 4.666 | 7.611 | 0.7830 | 6.507 | 10.335 | 0.0214 | 0.9720 | 4.709 |
| rtdl_mlp | 2249730 | 299.500 | 23 | 4.715 | 7.745 | 0.7753 | 6.648 | 10.434 | 0.0213 | 0.9647 | 4.792 |
| lightgbm | — | 542.400 | {'regression': 2708, 'death': 751} | 5.024 | 7.864 | 0.7684 | 6.969 | 10.523 | 0.0209 | 0.9725 | 5.134 |
| ensemble(6) | — | — | — | 4.103 | 6.665 | 0.8336 | 6.238 | 9.660 | 0.0189 | 0.9787 | — |

## 按来源类型（测试集）

| 模型 | 类型 | pair MAE | pair RMSE | pair R² | row MAE | death Brier |
|---|---|---|---|---|---|---|
| set_transformer | mutation | 5.197 | 8.184 | 0.7563 | 7.773 | 0.0282 |
| set_transformer | real | 4.147 | 6.932 | 0.8194 | 6.059 | 0.0188 |
| rtdl_resnet | mutation | 5.665 | 8.580 | 0.7321 | 8.152 | 0.0300 |
| rtdl_resnet | real | 4.124 | 6.862 | 0.8230 | 6.094 | 0.0189 |
| tabm | mutation | 5.633 | 8.533 | 0.7351 | 8.185 | 0.0281 |
| tabm | real | 4.338 | 7.075 | 0.8119 | 6.292 | 0.0189 |
| repo_mlp | mutation | 5.864 | 9.244 | 0.6891 | 8.243 | 0.0324 |
| repo_mlp | real | 4.527 | 7.399 | 0.7942 | 6.306 | 0.0201 |
| rtdl_mlp | mutation | 5.944 | 9.256 | 0.6883 | 8.355 | 0.0306 |
| rtdl_mlp | real | 4.573 | 7.551 | 0.7857 | 6.451 | 0.0203 |
| lightgbm | mutation | 5.943 | 8.970 | 0.7073 | 8.503 | 0.0308 |
| lightgbm | real | 4.917 | 7.725 | 0.7757 | 6.792 | 0.0197 |

## 按幕（测试集 pair MAE）

| 模型 | GLORY | HIVE | OVERGROWTH | UNDERDOCKS |
|---|---|---|---|---|
| set_transformer | 6.300 | 4.931 | 3.308 | 3.125 |
| rtdl_resnet | 6.468 | 4.839 | 3.279 | 3.230 |
| tabm | 6.819 | 5.092 | 3.420 | 3.293 |
| repo_mlp | 6.828 | 5.166 | 3.596 | 3.733 |
| rtdl_mlp | 6.797 | 5.402 | 3.702 | 3.606 |
| lightgbm | 7.277 | 5.477 | 4.151 | 3.910 |

## 说明

- 各模型均为现有实现的适配：`repo_mlp` 为仓库 `damage_model.model.DamageNet`；`rtdl_mlp`/`rtdl_resnet` 来自 `rtdl_revisiting_models`；`tabm` 来自 `tabm`；`set_transformer` 为官方 Set Transformer 模块加 key padding mask；`lightgbm` 为两棵 LightGBM（回归 + 死亡二分类）。
- 标签为 `净掉血 / 初始最大生命`，同一输入的重复种子按 1/种子数加权。早停依据验证集 pair MAE。
- `within_pair_rmse_hp` 是同输入有限种子的组内波动参考，不能据此确定总体不可约误差下限；`loo_seed_mean_mae_hp` 是用同输入其他种子均值预测单场的 MAE。四种子均值本身也有采样误差，这两项不是模型必须达到的目标。
- 运行记录：{"repo_mlp": {"exit_code": 0, "seconds": 345.0, "device": "cuda:0"}, "rtdl_mlp": {"exit_code": 0, "seconds": 345.0, "device": "cuda:1"}, "rtdl_resnet": {"exit_code": 0, "seconds": 545.0, "device": "cuda:2"}, "lightgbm": {"exit_code": 0, "seconds": 555.1, "device": "cpu"}, "tabm": {"exit_code": 0, "seconds": 690.1, "device": "cuda:0"}, "set_transformer": {"exit_code": 0, "seconds": 715.1, "device": "cuda:1"}}
