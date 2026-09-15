# 模型比较

> 本报告保留该固定快照的原指标与样例，路径是生成时的出处，不是当前采集工作目录。现行环境与指标解释见[训练说明](../../README.md)；不同快照的留出集不能直接作同条件比较。

快照：`/data2/pl/ImageTask/wxq/Projects/Sts2Bot/data/train-snapshots/20260913-121204`（2026-09-13T12:13:40.278174+00:00，770682 场，77039 个构筑，2071 个连通组）

来源：real-v4 224847 场、real-v3 400132 场、mut-v2 84972 场、mut-v1 60731 场

划分（按源局连通组）：train 549000 场 / 137281 对 / 54788 构筑 / 1675 组；validation 82950 场 / 20742 对 / 8356 构筑 / 190 组；test 138732 场 / 34690 对 / 13895 构筑 / 206 组

指标单位为 HP。pair 指标先对同一 (构筑, 目标) 的全部种子取均值再比较，row 指标按每场对战计算并以 1/种子数加权。

测试集组内波动参考：within_pair_rmse_hp=8.576，loo_seed_mean_mae_hp=6.285，multi_seed_rows=138730，pairs_with_multiple_seeds=34688

## 测试集（留出连通组）

| 模型 | 参数量 | 训练秒数 | 最佳轮次 | 测试 pair MAE | 测试 pair RMSE | 测试 pair R² | 测试 row MAE | 测试 row RMSE | 测试 death Brier | 测试 death AUC | 验证 pair MAE |
|---|---|---|---|---|---|---|---|---|---|---|---|
| set_transformer | 352514 | 407.700 | 16 | 4.543 | 7.209 | 0.8174 | 6.737 | 10.350 | 0.0207 | 0.9777 | 4.416 |
| rtdl_resnet | 1694466 | 89.800 | 25 | 4.646 | 7.466 | 0.8042 | 6.798 | 10.531 | 0.0218 | 0.9731 | 4.444 |
| tabm | 2606880 | 403.100 | 22 | 4.780 | 7.489 | 0.8030 | 6.973 | 10.547 | 0.0210 | 0.9756 | 4.621 |
| repo_mlp | 468354 | 355.600 | 16 | 4.904 | 7.921 | 0.7796 | 6.935 | 10.858 | 0.0231 | 0.9704 | 4.716 |
| rtdl_mlp | 2332674 | 200.300 | 25 | 4.972 | 7.967 | 0.7770 | 7.072 | 10.892 | 0.0228 | 0.9632 | 4.817 |
| lightgbm | — | 363.700 | {'regression': 1939, 'death': 874} | 5.446 | 8.300 | 0.7580 | 7.528 | 11.137 | 0.0229 | 0.9687 | 5.345 |
| ensemble(6) | — | — | — | 4.410 | 6.971 | 0.8293 | 6.714 | 10.185 | 0.0202 | 0.9774 | — |

## 按来源类型（测试集）

| 模型 | 类型 | pair MAE | pair RMSE | pair R² | row MAE | death Brier |
|---|---|---|---|---|---|---|
| set_transformer | mutation | 5.705 | 8.680 | 0.7567 | 8.393 | 0.0288 |
| set_transformer | real | 4.259 | 6.802 | 0.8338 | 6.333 | 0.0187 |
| rtdl_resnet | mutation | 5.973 | 9.037 | 0.7363 | 8.437 | 0.0304 |
| rtdl_resnet | real | 4.322 | 7.030 | 0.8224 | 6.397 | 0.0197 |
| tabm | mutation | 6.110 | 9.113 | 0.7319 | 8.735 | 0.0291 |
| tabm | real | 4.455 | 7.036 | 0.8221 | 6.543 | 0.0191 |
| repo_mlp | mutation | 6.311 | 9.686 | 0.6971 | 8.691 | 0.0330 |
| repo_mlp | real | 4.560 | 7.427 | 0.8018 | 6.507 | 0.0207 |
| rtdl_mlp | mutation | 6.332 | 9.670 | 0.6981 | 8.795 | 0.0317 |
| rtdl_mlp | real | 4.640 | 7.493 | 0.7983 | 6.651 | 0.0206 |
| lightgbm | mutation | 6.769 | 9.799 | 0.6899 | 9.300 | 0.0311 |
| lightgbm | real | 5.124 | 7.890 | 0.7763 | 7.095 | 0.0209 |

## 按幕（测试集 pair MAE）

| 模型 | GLORY | HIVE | OVERGROWTH | UNDERDOCKS |
|---|---|---|---|---|
| set_transformer | 6.481 | 4.935 | 3.386 | 3.264 |
| rtdl_resnet | 6.567 | 5.020 | 3.547 | 3.329 |
| tabm | 6.772 | 5.244 | 3.505 | 3.501 |
| repo_mlp | 7.063 | 5.253 | 3.706 | 3.478 |
| rtdl_mlp | 7.140 | 5.328 | 3.760 | 3.549 |
| lightgbm | 7.531 | 5.774 | 4.284 | 4.094 |

## 说明

- 各模型均为现有实现的适配：`repo_mlp` 为仓库 `damage_model.model.DamageNet`；`rtdl_mlp`/`rtdl_resnet` 来自 `rtdl_revisiting_models`；`tabm` 来自 `tabm`；`set_transformer` 为官方 Set Transformer 模块加 key padding mask；`lightgbm` 为两棵 LightGBM（回归 + 死亡二分类）。
- 标签为 `净掉血 / 初始最大生命`，同一输入的重复种子按 1/种子数加权。早停依据验证集 pair MAE。
- `within_pair_rmse_hp` 是同输入有限种子的组内波动参考，不能据此确定总体不可约误差下限；`loo_seed_mean_mae_hp` 是用同输入其他种子均值预测单场的 MAE。四种子均值本身也有采样误差，这两项不是模型必须达到的目标。
- 运行记录：{"rtdl_mlp": {"exit_code": 0, "seconds": 310.0, "device": "cuda:1"}, "lightgbm": {"exit_code": 0, "seconds": 485.1, "device": "cpu"}, "repo_mlp": {"exit_code": 0, "seconds": 485.1, "device": "cuda:0"}, "rtdl_resnet": {"exit_code": 0, "seconds": 260.1, "device": "cuda:1"}, "tabm": {"exit_code": 0, "seconds": 425.0, "device": "cuda:0"}, "set_transformer": {"exit_code": 0, "seconds": 425.0, "device": "cuda:1"}}
