# 预测样例与误差分析

快照 `data/train-snapshots/20260911-065245`，测试集 41954 场 / 10490 对。主模型 **set_transformer**（pair MAE 4.26 HP，中位数 2.15，偏差 -0.49）。对比模型：lightgbm, repo_mlp, rtdl_mlp, rtdl_resnet, set_transformer, tabm, ensemble。误差 = 预测 − 同输入全部种子的均值，单位 HP。

## 误差分布（主模型，pair 级）

| 分位 | 25% | 50% | 75% | 90% | 95% | 99% |
|---|---|---|---|---|---|---|
| |误差| | 0.80 | 2.15 | 5.43 | 10.91 | 15.44 | 27.05 |

|误差| ≤ 2 HP 的 pair 占 48.0%，≤ 5 HP 占 72.9%，> 15 HP 占 5.4%。

注意“标签”本身是 4 个种子的均值，也带噪声：按组内 std/√n 估计，即使模型给出真实期望值，与 4 种子均值之间的 MAE 也约为 **2.30 HP**（正态近似 √(2/π)·std/√n 的平均）。因此主模型 pair MAE 4.26 中相当一部分来自标签噪声，而非模型误差。同理，“按标签均值分桶”中高标签桶的负偏差有一部分是选择效应（标签均值偶然偏高的 pair 被选进高桶），应以“按预测值分桶”判断校准。

## 校准：按预测值分桶

每桶给出 pair 数、平均预测、平均标签均值、偏差、MAE。理想情况下平均预测 ≈ 平均标签。

| 预测区间 | pairs | 平均预测 | 平均标签 | 偏差 | MAE |
|---|---|---|---|---|---|
| [0.0, 5.0) | 4944 | 2.11 | 2.60 | -0.49 | 1.66 |
| [5.0, 10.0) | 1705 | 7.28 | 8.24 | -0.97 | 4.02 |
| [10.0, 15.0) | 1004 | 12.34 | 12.76 | -0.41 | 5.39 |
| [15.0, 20.0) | 724 | 17.36 | 17.94 | -0.58 | 6.48 |
| [20.0, 30.0) | 802 | 24.45 | 25.25 | -0.80 | 7.50 |
| [30.0, 40.0) | 506 | 34.68 | 35.86 | -1.18 | 10.49 |
| [40.0, 50.0) | 340 | 44.80 | 44.32 | 0.49 | 11.66 |
| [50.0, 60.0) | 252 | 54.61 | 52.72 | 1.89 | 11.80 |
| [60.0, 70.01) | 213 | 65.06 | 63.26 | 1.80 | 5.82 |

## 校准：按标签均值分桶

看模型在高掉血/死亡输入上是否系统性低估（向均值回归）。

| 标签区间 | pairs | 平均标签 | 平均预测 | 偏差 | MAE | 组内 std |
|---|---|---|---|---|---|---|
| [0.0, 5.0) | 4836 | 1.73 | 2.81 | 1.08 | 1.75 | 2.11 |
| [5.0, 10.0) | 1695 | 7.16 | 7.62 | 0.46 | 3.47 | 5.84 |
| [10.0, 15.0) | 1038 | 12.14 | 11.93 | -0.21 | 4.88 | 7.57 |
| [15.0, 20.0) | 651 | 17.23 | 16.40 | -0.83 | 5.95 | 9.09 |
| [20.0, 30.0) | 870 | 24.31 | 22.59 | -1.72 | 7.49 | 11.11 |
| [30.0, 40.0) | 497 | 34.31 | 32.28 | -2.02 | 9.00 | 13.65 |
| [40.0, 50.0) | 326 | 44.50 | 38.99 | -5.51 | 10.91 | 16.20 |
| [50.0, 60.0) | 220 | 54.48 | 44.54 | -9.94 | 12.41 | 14.72 |
| [60.0, 70.01) | 357 | 67.02 | 56.12 | -10.90 | 11.42 | 4.57 |

## 死亡概率校准（row 级）

| 预测死亡概率 | rows | 平均预测 | 实际死亡率 |
|---|---|---|---|
| [0.0, 0.02) | 38196 | 0.00 | 0.00 |
| [0.02, 0.05) | 444 | 0.03 | 0.13 |
| [0.05, 0.1) | 692 | 0.08 | 0.14 |
| [0.1, 0.2) | 788 | 0.15 | 0.21 |
| [0.2, 0.4) | 744 | 0.29 | 0.36 |
| [0.4, 0.6) | 448 | 0.49 | 0.49 |
| [0.6, 0.8) | 322 | 0.70 | 0.67 |
| [0.8, 1.01) | 320 | 0.91 | 0.86 |

含死亡的 pair 660 个（6.3%），其 pair MAE 11.76，偏差 -8.08；无死亡 pair MAE 3.75。全部种子死亡的 pair 138 个，平均预测 58.7 HP。

## 按怪物编组（主模型，pair 级）

按 MAE 从高到低；`弱` 为 weak 编组。

| 幕 | 编组 | 类型 | pairs | 平均标签 | 组内 std | 偏差 | MAE | 死亡场/总场 |
|---|---|---|---|---|---|---|---|---|
| HIVE | KNOWLEDGE_DEMON_BOSS | Boss | 79 | 50.04 | 13.74 | -7.40 | 13.38 | 125/316 |
| GLORY | AEONGLASS_BOSS | Boss | 82 | 49.54 | 12.84 | 4.11 | 12.64 | 164/328 |
| HIVE | THE_INSATIABLE_BOSS | Boss | 95 | 42.69 | 14.73 | 4.33 | 11.04 | 121/380 |
| GLORY | TEST_SUBJECT_BOSS | Boss | 93 | 51.31 | 12.76 | 0.87 | 10.56 | 178/372 |
| GLORY | QUEEN_BOSS | Boss | 88 | 46.12 | 12.63 | 1.74 | 10.42 | 100/350 |
| OVERGROWTH | THE_KIN_BOSS | Boss | 60 | 38.28 | 9.70 | 2.77 | 10.27 | 42/240 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | Boss | 81 | 42.25 | 9.00 | -5.94 | 10.14 | 104/324 |
| GLORY | KNIGHTS_ELITE | Elite | 154 | 22.67 | 13.01 | -0.94 | 9.97 | 52/616 |
| GLORY | MECHA_KNIGHT_ELITE | Elite | 151 | 22.26 | 11.84 | 0.98 | 9.84 | 14/604 |
| GLORY | CONSTRUCT_MENAGERIE_NORMAL | Monster | 44 | 19.07 | 10.68 | -6.72 | 9.58 | 1/176 |
| HIVE | KAISER_CRAB_BOSS | Boss | 61 | 46.11 | 11.27 | 1.39 | 9.34 | 50/244 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | Boss | 49 | 39.35 | 8.95 | -6.59 | 9.16 | 30/196 |
| UNDERDOCKS | SOUL_FYSH_BOSS | Boss | 62 | 39.21 | 10.59 | -2.62 | 9.07 | 34/248 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | Boss | 68 | 40.83 | 9.25 | 1.06 | 8.59 | 41/272 |
| HIVE | DECIMILLIPEDE_ELITE | Elite | 212 | 24.90 | 10.26 | -0.04 | 7.89 | 30/848 |
| OVERGROWTH | PHROG_PARASITE_ELITE | Elite | 196 | 22.09 | 9.89 | -4.37 | 7.87 | 83/784 |
| HIVE | ENTOMANCER_ELITE | Elite | 234 | 21.04 | 9.39 | -2.10 | 7.73 | 61/936 |
| HIVE | SLUMBERING_BEETLE_NORMAL | Monster | 86 | 13.85 | 9.14 | 3.41 | 7.46 | 2/344 |
| GLORY | AXEBOTS_NORMAL | Monster | 78 | 11.76 | 8.61 | -1.05 | 7.41 | 2/312 |
| HIVE | INFESTED_PRISMS_ELITE | Elite | 232 | 22.22 | 7.92 | 0.37 | 6.66 | 7/928 |
| GLORY | SOUL_NEXUS_ELITE | Elite | 129 | 14.21 | 8.24 | 1.52 | 6.64 | 0/516 |
| GLORY | GLOBE_HEAD_NORMAL | Monster | 72 | 10.16 | 5.49 | -3.79 | 6.55 | 0/288 |
| OVERGROWTH | VANTOM_BOSS | Boss | 53 | 31.65 | 10.94 | -2.32 | 6.42 | 12/212 |
| UNDERDOCKS | PHANTASMAL_GARDENERS_ELITE | Elite | 241 | 27.13 | 8.32 | -0.99 | 6.17 | 95/964 |
| OVERGROWTH | BYGONE_EFFIGY_ELITE | Elite | 214 | 20.88 | 7.81 | 0.14 | 6.07 | 15/856 |
| GLORY | THE_LOST_AND_FORGOTTEN_NORMAL | Monster | 91 | 11.99 | 9.34 | -1.73 | 6.04 | 10/364 |
| UNDERDOCKS | CULTISTS_NORMAL | Monster | 77 | 17.59 | 8.31 | 0.49 | 5.78 | 16/308 |
| GLORY | SLIMED_BERSERKER_NORMAL | Monster | 99 | 7.72 | 6.20 | -0.79 | 5.72 | 0/396 |
| OVERGROWTH | OVERGROWTH_CRAWLERS | Monster | 73 | 15.22 | 7.61 | -1.25 | 5.51 | 10/292 |
| OVERGROWTH | BYRDONIS_ELITE | Elite | 203 | 24.79 | 7.02 | -0.31 | 5.50 | 14/812 |
| UNDERDOCKS | TERROR_EEL_ELITE | Elite | 244 | 22.55 | 6.95 | -1.83 | 5.42 | 34/976 |
| HIVE | OVICOPTER_NORMAL | Monster | 111 | 11.12 | 7.57 | -2.24 | 5.15 | 3/444 |
| GLORY | OWL_MAGISTRATE_NORMAL | Monster | 59 | 7.78 | 5.60 | -0.38 | 4.82 | 0/236 |
| HIVE | THE_OBSCURA_NORMAL | Monster | 115 | 9.45 | 7.73 | -1.01 | 4.65 | 0/460 |
| GLORY | FABRICATOR_NORMAL | Monster | 58 | 6.76 | 6.74 | -2.08 | 4.63 | 0/231 |
| GLORY | SCROLLS_OF_BITING_NORMAL | Monster | 102 | 6.40 | 5.68 | -0.60 | 4.44 | 0/408 |
| HIVE | MYTES_NORMAL | Monster | 132 | 9.39 | 5.92 | -1.10 | 4.21 | 1/528 |
| HIVE | HUNTER_KILLER_NORMAL | Monster | 130 | 10.15 | 6.73 | 1.21 | 4.17 | 0/520 |
| GLORY | DEVOTED_SCULPTOR_WEAK | Monster弱 | 169 | 5.96 | 5.48 | -0.66 | 4.15 | 4/676 |
| GLORY | FROG_KNIGHT_NORMAL | Monster | 54 | 5.50 | 4.07 | 0.44 | 4.02 | 0/216 |
| OVERGROWTH | NIBBITS_NORMAL | Monster | 71 | 13.12 | 6.24 | 0.19 | 3.85 | 2/284 |
| OVERGROWTH | SNAPPING_JAXFRUIT_NORMAL | Monster | 50 | 11.20 | 5.65 | 0.49 | 3.74 | 0/200 |
| HIVE | TUNNELER_WEAK | Monster弱 | 218 | 7.30 | 5.19 | -1.01 | 3.63 | 0/872 |
| HIVE | CHOMPERS_NORMAL | Monster | 94 | 11.17 | 5.45 | -1.17 | 3.63 | 0/376 |
| UNDERDOCKS | SEAPUNK_NORMAL | Monster | 66 | 15.53 | 5.89 | -0.58 | 3.50 | 0/264 |
| HIVE | BOWLBUGS_NORMAL | Monster | 81 | 8.89 | 6.59 | -0.71 | 3.46 | 0/324 |
| UNDERDOCKS | SKULKING_COLONY_ELITE | Elite | 207 | 15.32 | 5.39 | -0.08 | 3.43 | 0/828 |
| HIVE | SPINY_TOAD_NORMAL | Monster | 145 | 6.74 | 4.90 | -1.08 | 3.40 | 0/580 |
| OVERGROWTH | RUBY_RAIDERS_NORMAL | Monster | 86 | 13.08 | 6.34 | -1.08 | 3.32 | 0/344 |
| UNDERDOCKS | HAUNTED_SHIP_NORMAL | Monster | 103 | 10.37 | 5.14 | -0.84 | 3.11 | 0/412 |
| HIVE | EXOSKELETONS_NORMAL | Monster | 107 | 4.71 | 4.06 | 0.17 | 3.04 | 0/428 |
| OVERGROWTH | FLYCONID_NORMAL | Monster | 65 | 12.91 | 5.40 | -0.77 | 3.01 | 0/260 |
| UNDERDOCKS | LIVING_FOG_NORMAL | Monster | 85 | 5.50 | 2.88 | -1.55 | 3.01 | 0/340 |
| UNDERDOCKS | GREMLIN_MERC_NORMAL | Monster | 92 | 6.81 | 3.80 | -0.24 | 2.92 | 0/368 |
| UNDERDOCKS | TWO_TAILED_RATS_NORMAL | Monster | 96 | 8.16 | 4.83 | -0.58 | 2.89 | 4/384 |
| HIVE | LOUSE_PROGENITOR_NORMAL | Monster | 110 | 6.11 | 4.57 | -0.55 | 2.88 | 0/440 |
| OVERGROWTH | SLIMES_NORMAL | Monster | 67 | 5.95 | 3.77 | 0.61 | 2.83 | 0/268 |
| UNDERDOCKS | FOSSIL_STALKER_NORMAL | Monster | 107 | 6.91 | 4.77 | 0.95 | 2.55 | 0/428 |
| HIVE | BOWLBUGS_WEAK | Monster弱 | 207 | 3.86 | 3.78 | 0.28 | 2.47 | 0/828 |
| GLORY | SCROLLS_OF_BITING_WEAK | Monster弱 | 179 | 3.88 | 3.56 | -0.59 | 2.47 | 0/716 |
| UNDERDOCKS | CORPSE_SLUGS_NORMAL | Monster | 75 | 7.22 | 3.52 | -0.63 | 2.28 | 0/300 |
| OVERGROWTH | INKLETS_NORMAL | Monster | 63 | 7.31 | 3.54 | -0.48 | 2.25 | 0/252 |
| OVERGROWTH | FOGMOG_NORMAL | Monster | 41 | 5.88 | 3.98 | -1.69 | 2.22 | 0/164 |
| OVERGROWTH | MAWLER_NORMAL | Monster | 73 | 8.38 | 4.71 | -0.48 | 2.18 | 0/292 |
| OVERGROWTH | CUBEX_CONSTRUCT_NORMAL | Monster | 80 | 4.88 | 3.77 | -0.67 | 1.99 | 0/320 |
| HIVE | THIEVING_HOPPER_WEAK | Monster弱 | 226 | 3.20 | 3.02 | -0.26 | 1.98 | 0/904 |
| OVERGROWTH | VINE_SHAMBLER_NORMAL | Monster | 81 | 5.48 | 3.08 | 0.20 | 1.97 | 0/324 |
| OVERGROWTH | SLITHERING_STRANGLER_NORMAL | Monster | 70 | 4.45 | 4.12 | -0.66 | 1.85 | 0/280 |
| UNDERDOCKS | PUNCH_CONSTRUCT_NORMAL | Monster | 110 | 5.33 | 3.22 | 0.19 | 1.84 | 0/440 |
| UNDERDOCKS | SEWER_CLAM_NORMAL | Monster | 119 | 3.26 | 2.96 | 0.22 | 1.77 | 0/476 |
| GLORY | TURRET_OPERATOR_WEAK | Monster弱 | 227 | 2.84 | 2.92 | 0.18 | 1.70 | 0/908 |
| UNDERDOCKS | CORPSE_SLUGS_WEAK | Monster弱 | 303 | 3.56 | 2.35 | -0.39 | 1.43 | 0/1212 |
| HIVE | EXOSKELETONS_WEAK | Monster弱 | 236 | 1.87 | 2.02 | -0.47 | 1.26 | 0/944 |
| OVERGROWTH | SHRINKER_BEETLE_WEAK | Monster弱 | 232 | 1.68 | 1.91 | -0.04 | 1.05 | 0/928 |
| UNDERDOCKS | SEAPUNK_WEAK | Monster弱 | 297 | 1.91 | 2.30 | -0.12 | 1.03 | 0/1186 |
| UNDERDOCKS | SLUDGE_SPINNER_WEAK | Monster弱 | 276 | 2.09 | 2.37 | -0.06 | 1.02 | 0/1104 |
| UNDERDOCKS | TOADPOLES_WEAK | Monster弱 | 324 | 2.34 | 2.11 | 0.03 | 0.97 | 0/1295 |
| OVERGROWTH | FUZZY_WURM_CRAWLER_WEAK | Monster弱 | 271 | 1.44 | 1.60 | -0.30 | 0.91 | 0/1084 |
| OVERGROWTH | SLIMES_WEAK | Monster弱 | 240 | 1.61 | 1.98 | -0.27 | 0.90 | 0/960 |
| OVERGROWTH | NIBBITS_WEAK | Monster弱 | 279 | 1.47 | 1.97 | -0.23 | 0.77 | 0/1116 |

## 编组内区分能力：模型是否只在预测“这个怪难不难”

基线 = 对每个编组恒定预测其**训练集**标签均值（只看怪、不看构筑）。若模型对同一编组的不同构筑预测几乎不变，其预测 std 会远小于标签 std，编组内相关系数接近 0，编组内 R² 也接近 0（R² = 1 − 模型 MSE / 基线 MSE，>0 表示比基线好）。

整体：模型 pair MAE 4.26，编组均值基线 pair MAE 7.21；基线 pair R² 0.551，模型 pair R² 0.813。编组内相关系数中位数 0.74，编组内 R² 中位数 0.53；模型在 78/80 个编组上优于基线，在 5 个编组上几乎没有区分能力（R² < 0.1）。模型预测 std / 标签 std 的中位数 0.79（接近 0 表示对该编组几乎恒定预测）。

按编组内 R² 从低到高（最像“不分青红皂白”的排在前面）：

| 幕 | 编组 | 类型 | pairs | 标签 std | 预测 std | 相关 | 编组内 R² | MAE 模型 | MAE 基线 |
|---|---|---|---|---|---|---|---|---|---|
| GLORY | FABRICATOR_NORMAL | Monster | 58 | 5.94 | 4.77 | 0.24 | -0.29 | 4.63 | 4.73 |
| HIVE | EXOSKELETONS_NORMAL | Monster | 107 | 4.56 | 4.79 | 0.48 | -0.03 | 3.04 | 4.01 |
| HIVE | KNOWLEDGE_DEMON_BOSS | Boss | 79 | 16.66 | 13.61 | 0.51 | 0.02 | 13.38 | 14.62 |
| GLORY | THE_LOST_AND_FORGOTTEN_NORMAL | Monster | 91 | 11.27 | 5.90 | 0.33 | 0.06 | 6.04 | 6.70 |
| GLORY | FROG_KNIGHT_NORMAL | Monster | 54 | 5.30 | 5.10 | 0.51 | 0.08 | 4.02 | 4.64 |
| GLORY | AXEBOTS_NORMAL | Monster | 78 | 10.77 | 6.54 | 0.42 | 0.13 | 7.41 | 8.18 |
| HIVE | SLUMBERING_BEETLE_NORMAL | Monster | 86 | 11.22 | 12.10 | 0.65 | 0.16 | 7.46 | 9.17 |
| GLORY | SLIMED_BERSERKER_NORMAL | Monster | 99 | 8.73 | 6.43 | 0.48 | 0.16 | 5.72 | 7.13 |
| GLORY | GLOBE_HEAD_NORMAL | Monster | 72 | 10.51 | 4.76 | 0.43 | 0.18 | 6.55 | 7.84 |
| UNDERDOCKS | LIVING_FOG_NORMAL | Monster | 85 | 4.78 | 3.05 | 0.58 | 0.22 | 3.01 | 4.02 |
| GLORY | MECHA_KNIGHT_ELITE | Elite | 151 | 15.47 | 12.62 | 0.57 | 0.26 | 9.84 | 12.72 |
| GLORY | DEVOTED_SCULPTOR_WEAK | Monster弱 | 169 | 8.59 | 5.06 | 0.55 | 0.30 | 4.15 | 6.08 |
| HIVE | EXOSKELETONS_WEAK | Monster弱 | 236 | 2.46 | 1.60 | 0.58 | 0.30 | 1.26 | 1.82 |
| HIVE | BOWLBUGS_WEAK | Monster弱 | 207 | 4.19 | 3.14 | 0.58 | 0.30 | 2.47 | 3.06 |
| OVERGROWTH | SLIMES_WEAK | Monster弱 | 240 | 1.45 | 0.97 | 0.59 | 0.31 | 0.90 | 1.16 |
| GLORY | CONSTRUCT_MENAGERIE_NORMAL | Monster | 44 | 12.72 | 9.36 | 0.71 | 0.34 | 9.58 | 10.72 |
| OVERGROWTH | NIBBITS_WEAK | Monster弱 | 279 | 1.29 | 0.97 | 0.63 | 0.35 | 0.77 | 1.02 |
| HIVE | THIEVING_HOPPER_WEAK | Monster弱 | 226 | 3.32 | 1.97 | 0.59 | 0.35 | 1.98 | 2.57 |
| OVERGROWTH | SHRINKER_BEETLE_WEAK | Monster弱 | 232 | 1.73 | 1.14 | 0.60 | 0.35 | 1.05 | 1.37 |
| HIVE | SPINY_TOAD_NORMAL | Monster | 145 | 5.41 | 3.82 | 0.63 | 0.36 | 3.40 | 4.39 |
| UNDERDOCKS | SEAPUNK_WEAK | Monster弱 | 297 | 1.72 | 1.24 | 0.62 | 0.37 | 1.03 | 1.33 |
| HIVE | THE_OBSCURA_NORMAL | Monster | 115 | 7.86 | 8.82 | 0.73 | 0.37 | 4.65 | 6.47 |
| GLORY | QUEEN_BOSS | Boss | 88 | 17.41 | 13.20 | 0.63 | 0.37 | 10.42 | 15.33 |
| UNDERDOCKS | SEWER_CLAM_NORMAL | Monster | 119 | 3.32 | 3.12 | 0.67 | 0.37 | 1.77 | 2.62 |
| UNDERDOCKS | CORPSE_SLUGS_WEAK | Monster弱 | 303 | 2.27 | 1.66 | 0.64 | 0.38 | 1.43 | 1.87 |
| UNDERDOCKS | SLUDGE_SPINNER_WEAK | Monster弱 | 276 | 1.64 | 1.10 | 0.62 | 0.40 | 1.02 | 1.39 |
| GLORY | AEONGLASS_BOSS | Boss | 82 | 21.12 | 12.53 | 0.66 | 0.41 | 12.64 | 18.34 |
| HIVE | MYTES_NORMAL | Monster | 132 | 9.16 | 6.62 | 0.66 | 0.43 | 4.21 | 6.98 |
| OVERGROWTH | FUZZY_WURM_CRAWLER_WEAK | Monster弱 | 271 | 1.76 | 1.20 | 0.68 | 0.43 | 0.91 | 1.37 |
| HIVE | LOUSE_PROGENITOR_NORMAL | Monster | 110 | 5.44 | 3.90 | 0.62 | 0.44 | 2.88 | 4.73 |
| GLORY | TEST_SUBJECT_BOSS | Boss | 93 | 18.86 | 14.09 | 0.66 | 0.44 | 10.56 | 15.91 |
| GLORY | SOUL_NEXUS_ELITE | Elite | 129 | 11.06 | 10.39 | 0.72 | 0.44 | 6.64 | 9.01 |
| HIVE | TUNNELER_WEAK | Monster弱 | 218 | 6.57 | 4.33 | 0.69 | 0.45 | 3.63 | 4.89 |
| HIVE | THE_INSATIABLE_BOSS | Boss | 95 | 18.51 | 13.82 | 0.70 | 0.46 | 11.04 | 15.96 |
| GLORY | SCROLLS_OF_BITING_NORMAL | Monster | 102 | 8.29 | 4.94 | 0.63 | 0.47 | 4.44 | 8.03 |
| HIVE | KAISER_CRAB_BOSS | Boss | 61 | 15.69 | 15.35 | 0.74 | 0.49 | 9.34 | 12.64 |
| GLORY | SCROLLS_OF_BITING_WEAK | Monster弱 | 179 | 5.42 | 3.79 | 0.71 | 0.49 | 2.47 | 4.19 |
| GLORY | KNIGHTS_ELITE | Elite | 154 | 18.57 | 13.55 | 0.71 | 0.51 | 9.97 | 15.93 |
| OVERGROWTH | THE_KIN_BOSS | Boss | 60 | 18.53 | 14.69 | 0.71 | 0.52 | 10.27 | 16.58 |
| HIVE | HUNTER_KILLER_NORMAL | Monster | 130 | 7.34 | 6.94 | 0.74 | 0.53 | 4.17 | 6.49 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | Boss | 49 | 18.24 | 15.81 | 0.81 | 0.53 | 9.16 | 15.75 |
| GLORY | OWL_MAGISTRATE_NORMAL | Monster | 59 | 9.58 | 5.46 | 0.75 | 0.53 | 4.82 | 7.04 |
| HIVE | BOWLBUGS_NORMAL | Monster | 81 | 7.59 | 6.96 | 0.75 | 0.54 | 3.46 | 5.42 |
| OVERGROWTH | CUBEX_CONSTRUCT_NORMAL | Monster | 80 | 4.39 | 3.24 | 0.75 | 0.55 | 1.99 | 3.39 |
| GLORY | TURRET_OPERATOR_WEAK | Monster弱 | 227 | 3.47 | 3.07 | 0.72 | 0.55 | 1.70 | 3.06 |
| UNDERDOCKS | TOADPOLES_WEAK | Monster弱 | 324 | 1.91 | 1.55 | 0.75 | 0.57 | 0.97 | 1.55 |
| HIVE | CHOMPERS_NORMAL | Monster | 94 | 7.54 | 6.07 | 0.78 | 0.58 | 3.63 | 6.10 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | Boss | 81 | 22.15 | 18.40 | 0.80 | 0.58 | 10.14 | 19.53 |
| UNDERDOCKS | GREMLIN_MERC_NORMAL | Monster | 92 | 6.26 | 4.84 | 0.77 | 0.59 | 2.92 | 5.25 |
| OVERGROWTH | FOGMOG_NORMAL | Monster | 41 | 6.28 | 4.22 | 0.84 | 0.61 | 2.22 | 4.98 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | Boss | 68 | 18.49 | 16.09 | 0.79 | 0.62 | 8.59 | 16.34 |
| HIVE | DECIMILLIPEDE_ELITE | Elite | 212 | 16.37 | 14.01 | 0.79 | 0.63 | 7.89 | 13.62 |
| UNDERDOCKS | SOUL_FYSH_BOSS | Boss | 62 | 18.00 | 13.36 | 0.80 | 0.63 | 9.07 | 15.01 |
| HIVE | ENTOMANCER_ELITE | Elite | 234 | 17.74 | 13.95 | 0.80 | 0.63 | 7.73 | 13.51 |
| HIVE | INFESTED_PRISMS_ELITE | Elite | 232 | 13.99 | 11.46 | 0.80 | 0.64 | 6.66 | 11.76 |
| OVERGROWTH | PHROG_PARASITE_ELITE | Elite | 196 | 20.00 | 15.89 | 0.83 | 0.64 | 7.87 | 16.94 |
| OVERGROWTH | SLITHERING_STRANGLER_NORMAL | Monster | 70 | 4.71 | 3.41 | 0.82 | 0.65 | 1.85 | 3.92 |
| UNDERDOCKS | FOSSIL_STALKER_NORMAL | Monster | 107 | 5.89 | 5.77 | 0.83 | 0.65 | 2.55 | 4.38 |
| UNDERDOCKS | HAUNTED_SHIP_NORMAL | Monster | 103 | 5.96 | 6.11 | 0.80 | 0.67 | 3.11 | 5.38 |
| HIVE | OVICOPTER_NORMAL | Monster | 111 | 12.19 | 9.12 | 0.85 | 0.68 | 5.15 | 9.15 |
| OVERGROWTH | SLIMES_NORMAL | Monster | 67 | 6.32 | 5.33 | 0.82 | 0.68 | 2.83 | 5.41 |
| OVERGROWTH | INKLETS_NORMAL | Monster | 63 | 5.05 | 4.23 | 0.84 | 0.70 | 2.25 | 4.25 |
| OVERGROWTH | BYRDONIS_ELITE | Elite | 203 | 14.64 | 12.78 | 0.84 | 0.72 | 5.50 | 11.66 |
| OVERGROWTH | VINE_SHAMBLER_NORMAL | Monster | 81 | 4.85 | 3.45 | 0.86 | 0.72 | 1.97 | 3.91 |
| UNDERDOCKS | PUNCH_CONSTRUCT_NORMAL | Monster | 110 | 4.34 | 3.31 | 0.85 | 0.72 | 1.84 | 3.74 |
| OVERGROWTH | BYGONE_EFFIGY_ELITE | Elite | 214 | 15.53 | 14.21 | 0.85 | 0.73 | 6.07 | 12.91 |
| OVERGROWTH | OVERGROWTH_CRAWLERS | Monster | 73 | 16.42 | 13.04 | 0.85 | 0.73 | 5.51 | 12.92 |
| UNDERDOCKS | SKULKING_COLONY_ELITE | Elite | 207 | 9.01 | 7.67 | 0.86 | 0.74 | 3.43 | 7.28 |
| OVERGROWTH | SNAPPING_JAXFRUIT_NORMAL | Monster | 50 | 9.27 | 7.52 | 0.85 | 0.74 | 3.74 | 7.97 |
| UNDERDOCKS | SEAPUNK_NORMAL | Monster | 66 | 9.58 | 8.22 | 0.86 | 0.75 | 3.50 | 7.92 |
| OVERGROWTH | VANTOM_BOSS | Boss | 53 | 15.85 | 13.05 | 0.87 | 0.75 | 6.42 | 13.15 |
| OVERGROWTH | RUBY_RAIDERS_NORMAL | Monster | 86 | 9.01 | 7.51 | 0.87 | 0.76 | 3.32 | 7.35 |
| OVERGROWTH | NIBBITS_NORMAL | Monster | 71 | 10.12 | 8.63 | 0.87 | 0.76 | 3.85 | 7.26 |
| UNDERDOCKS | TWO_TAILED_RATS_NORMAL | Monster | 96 | 9.46 | 8.13 | 0.88 | 0.77 | 2.89 | 6.24 |
| OVERGROWTH | MAWLER_NORMAL | Monster | 73 | 5.54 | 4.39 | 0.87 | 0.77 | 2.18 | 4.70 |
| UNDERDOCKS | TERROR_EEL_ELITE | Elite | 244 | 16.89 | 14.07 | 0.91 | 0.81 | 5.42 | 12.76 |
| UNDERDOCKS | CORPSE_SLUGS_NORMAL | Monster | 75 | 7.28 | 6.73 | 0.91 | 0.83 | 2.28 | 5.34 |
| UNDERDOCKS | PHANTASMAL_GARDENERS_ELITE | Elite | 241 | 21.00 | 18.92 | 0.91 | 0.83 | 6.17 | 17.65 |
| OVERGROWTH | FLYCONID_NORMAL | Monster | 65 | 9.67 | 8.12 | 0.91 | 0.83 | 3.01 | 7.25 |
| UNDERDOCKS | CULTISTS_NORMAL | Monster | 77 | 18.75 | 17.28 | 0.92 | 0.85 | 5.78 | 14.73 |

各 Boss 编组内的预测分布（分位数），对照标签均值分布：

| 幕 | Boss | pairs | 标签 10%/50%/90% | 预测 10%/50%/90% |
|---|---|---|---|---|
| GLORY | AEONGLASS_BOSS | 82 | 23 / 60 / 70 | 39 / 54 / 68 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | 49 | 16 / 39 / 66 | 14 / 31 / 52 |
| HIVE | KAISER_CRAB_BOSS | 61 | 28 / 48 / 69 | 25 / 50 / 64 |
| HIVE | KNOWLEDGE_DEMON_BOSS | 79 | 26 / 52 / 70 | 26 / 40 / 62 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | 81 | 13 / 44 / 70 | 12 / 32 / 63 |
| GLORY | QUEEN_BOSS | 88 | 22 / 45 / 69 | 30 / 47 / 65 |
| UNDERDOCKS | SOUL_FYSH_BOSS | 62 | 16 / 40 / 64 | 20 / 36 / 52 |
| GLORY | TEST_SUBJECT_BOSS | 93 | 19 / 56 / 70 | 33 / 54 / 67 |
| HIVE | THE_INSATIABLE_BOSS | 95 | 20 / 42 / 68 | 31 / 47 / 65 |
| OVERGROWTH | THE_KIN_BOSS | 60 | 16 / 36 / 67 | 23 / 40 / 59 |
| OVERGROWTH | VANTOM_BOSS | 53 | 14 / 30 / 57 | 15 / 27 / 46 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | 68 | 17 / 44 / 63 | 16 / 43 / 62 |

## 按房间类型、幕、来源类型

### 房间类型

| 房间类型 | pairs | 平均标签 | 偏差 | MAE | MAE lightgbm | MAE repo_mlp | MAE rtdl_mlp | MAE rtdl_resnet | MAE tabm | MAE ensemble |
|---|---|---|---|---|---|---|---|---|---|---|
| Boss | 871 | 43.91 | -0.42 | 10.31 | 12.17 | 11.26 | 11.21 | 10.25 | 10.84 | 9.99 |
| Elite | 2417 | 21.96 | -0.75 | 6.78 | 8.05 | 7.48 | 7.74 | 6.73 | 6.98 | 6.48 |
| Monster | 3518 | 8.85 | -0.59 | 3.82 | 4.45 | 4.13 | 4.12 | 3.84 | 4.04 | 3.69 |
| Monster(weak) | 3684 | 2.84 | -0.24 | 1.58 | 1.90 | 1.78 | 1.76 | 1.70 | 1.74 | 1.59 |

### 幕

| 幕 | pairs | 平均标签 | 偏差 | MAE | MAE lightgbm | MAE repo_mlp | MAE rtdl_mlp | MAE rtdl_resnet | MAE tabm | MAE ensemble |
|---|---|---|---|---|---|---|---|---|---|---|
| GLORY | 1929 | 15.59 | -0.24 | 6.30 | 7.28 | 6.83 | 6.80 | 6.47 | 6.82 | 6.19 |
| HIVE | 2911 | 13.65 | -0.43 | 4.93 | 5.48 | 5.17 | 5.40 | 4.84 | 5.09 | 4.62 |
| OVERGROWTH | 2617 | 10.98 | -0.67 | 3.31 | 4.15 | 3.60 | 3.70 | 3.28 | 3.42 | 3.20 |
| UNDERDOCKS | 3033 | 11.34 | -0.54 | 3.13 | 3.91 | 3.73 | 3.61 | 3.23 | 3.29 | 3.11 |

### 来源类型

| 来源类型 | pairs | 平均标签 | 偏差 | MAE | MAE lightgbm | MAE repo_mlp | MAE rtdl_mlp | MAE rtdl_resnet | MAE tabm | MAE ensemble |
|---|---|---|---|---|---|---|---|---|---|---|
| mutation | 1088 | 13.23 | -0.72 | 5.20 | 5.94 | 5.86 | 5.94 | 5.67 | 5.63 | 5.19 |
| real | 9402 | 12.61 | -0.46 | 4.15 | 4.92 | 4.53 | 4.57 | 4.12 | 4.34 | 3.99 |

### 牌组张数

| 牌组张数 | pairs | 平均标签 | 偏差 | MAE |
|---|---|---|---|---|
| [0, 12) | 32 | 4.50 | 0.39 | 1.70 |
| [12, 16) | 1872 | 7.13 | -0.59 | 2.02 |
| [16, 20) | 2719 | 11.93 | -0.71 | 3.54 |
| [20, 25) | 2748 | 13.35 | -0.55 | 4.65 |
| [25, 30) | 1815 | 15.38 | -0.62 | 5.45 |
| [30, 46) | 1304 | 17.16 | 0.38 | 6.52 |

### 遗物件数

| 遗物件数 | pairs | 平均标签 | 偏差 | MAE |
|---|---|---|---|---|
| [0, 3) | 2694 | 8.66 | -0.49 | 2.27 |
| [3, 5) | 1810 | 12.19 | -0.61 | 3.74 |
| [5, 8) | 2335 | 12.80 | -0.82 | 4.44 |
| [8, 12) | 1933 | 14.16 | -0.39 | 5.27 |
| [12, 40) | 1718 | 17.62 | -0.02 | 6.53 |

## 模型分歧

各模型预测极差的中位数 5.09 HP，90% 分位 16.41。分歧最大的 pair 与其真值：

**HIVE / ENTOMANCER_ELITE** (Elite; 怪物 ENTOMANCER) — real / real-v3 / 构筑 `89db72bd94c6`
- 牌组 25 张：ADRENALINE, ANTICIPATE, ASCENDERS_BANE, BACKFLIP, BLADE_DANCE, BLUR×3, DARK_SHACKLES, DEFEND_SILENT×5, ECHOING_SLASH, EXPERTISE, FOOTWORK×2, LEADING_STRIKE, NEUTRALIZE, PHANTOM_BLADES, POISONED_STAB, STRIKE_SILENT×2, SURVIVOR
- 遗物 9 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, GORGET, ODDLY_SMOOTH_STONE, HAPPY_FLOWER(TurnsSeen=0), POTION_BELT, REGAL_PILLOW, MEAL_TICKET, RUNIC_PYRAMID
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 28.0 (-42.0, 死亡 0.15), repo_mlp 12.6 (-57.4, 死亡 0.01), rtdl_mlp 30.8 (-39.2, 死亡 0.02), rtdl_resnet 11.1 (-58.9, 死亡 0.00), set_transformer 64.8 (-5.2, 死亡 0.77), tabm 37.2 (-32.8, 死亡 0.15), ensemble 30.8 (-39.2, 死亡 0.18)

**OVERGROWTH / PHROG_PARASITE_ELITE** (Elite; 怪物 PHROG_PARASITE, WRIGGLER) — real / real-v3 / 构筑 `f0dfc5e069fa`
- 牌组 19 张：ANTICIPATE, ASCENDERS_BANE, ASSASSINATE+1, BLUR, CLUMSY, DAGGER_SPRAY, DEFEND_SILENT×5, HAND_TRICK, INJURY, LEG_SWEEP, NEUTRALIZE, STRIKE_SILENT×3, SURVIVOR [NIMBLE 2]
- 遗物 4 件：RING_OF_THE_SNAKE, HEFTY_TABLET, ORICHALCUM, STONE_CALENDAR
- 标签（4 个种子净掉血）：[33, 6, 70, 70] → 均值 **44.8**，组内 std 31.2，死亡 2/4
- 预测（误差，死亡概率）：lightgbm 37.6 (-7.2, 死亡 0.10), repo_mlp 38.4 (-6.4, 死亡 0.06), rtdl_mlp 63.0 (+18.3, 死亡 0.60), rtdl_resnet 46.5 (+1.7, 死亡 0.50), set_transformer 9.4 (-35.4, 死亡 0.00), tabm 28.6 (-16.1, 死亡 0.06), ensemble 37.2 (-7.5, 死亡 0.22)

**OVERGROWTH / PHROG_PARASITE_ELITE** (Elite; 怪物 PHROG_PARASITE, WRIGGLER) — real / real-v3 / 构筑 `aaef0d66e209`
- 牌组 20 张：ANTICIPATE, ASCENDERS_BANE, ASSASSINATE+1, BLUR, CLUMSY, DAGGER_SPRAY, DEFEND_SILENT×5, HAND_TRICK, INJURY, LEG_SWEEP, NEUTRALIZE, PREPARED, STRIKE_SILENT×3, SURVIVOR [NIMBLE 2]
- 遗物 4 件：RING_OF_THE_SNAKE, HEFTY_TABLET, ORICHALCUM, STONE_CALENDAR
- 标签（4 个种子净掉血）：[17, 63, 70, 11] → 均值 **40.2**，组内 std 30.5，死亡 1/4
- 预测（误差，死亡概率）：lightgbm 33.0 (-7.3, 死亡 0.05), repo_mlp 37.8 (-2.4, 死亡 0.07), rtdl_mlp 61.6 (+21.3, 死亡 0.60), rtdl_resnet 46.6 (+6.3, 死亡 0.52), set_transformer 8.4 (-31.9, 死亡 0.00), tabm 28.5 (-11.8, 死亡 0.07), ensemble 36.0 (-4.3, 死亡 0.22)

**HIVE / ENTOMANCER_ELITE** (Elite; 怪物 ENTOMANCER) — real / real-v3 / 构筑 `36f2a48e174f`
- 牌组 17 张：ASCENDERS_BANE, CORROSIVE_WAVE, DEADLY_POISON+1, DEFEND_SILENT×5, DEFLECT, FOOTWORK, LEADING_STRIKE, LEG_SWEEP, NEUTRALIZE+1, STRIKE_SILENT×2, SURVIVOR, WELL_LAID_PLANS
- 遗物 7 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, JUZU_BRACELET, PENDULUM(TurnsSeen=1), RED_MASK, PHILOSOPHERS_STONE, TEA_OF_DISCOURTESY(CombatsLeft=1)
- 标签（4 个种子净掉血）：[30, 70, 35, 40] → 均值 **43.8**，组内 std 18.0，死亡 1/4
- 预测（误差，死亡概率）：lightgbm 41.0 (-2.7, 死亡 0.40), repo_mlp 46.4 (+2.7, 死亡 0.55), rtdl_mlp 69.4 (+25.6, 死亡 0.81), rtdl_resnet 36.0 (-7.7, 死亡 0.03), set_transformer 16.7 (-27.1, 死亡 0.00), tabm 47.9 (+4.1, 死亡 0.27), ensemble 42.9 (-0.9, 死亡 0.34)

## 最严重高估（预测 ≫ 标签）

模型认为会掉很多血，实际老师打得轻松。

**OVERGROWTH / BYRDONIS_ELITE** (Elite; 怪物 BYRDONIS) — real / real-v3 / 构筑 `dbf10b62ab94`
- 牌组 17 张：ASCENDERS_BANE, DEFEND_SILENT×5, DODGE_AND_ROLL [NIMBLE 2], GRAND_FINALE, INJURY, NEUTRALIZE, PREPARED, STRIKE_SILENT×3, SURVIVOR, THE_HUNT, UNTOUCHABLE
- 遗物 2 件：RING_OF_THE_SNAKE, HEFTY_TABLET
- 标签（4 个种子净掉血）：[5, 23, 4, 10] → 均值 **10.5**，组内 std 8.7，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 44.6 (+34.1, 死亡 0.16), repo_mlp 53.9 (+43.4, 死亡 0.19), rtdl_mlp 67.0 (+56.5, 死亡 0.64), rtdl_resnet 61.3 (+50.8, 死亡 0.51), set_transformer 58.8 (+48.3, 死亡 0.34), tabm 56.9 (+46.4, 死亡 0.31), ensemble 57.1 (+46.6, 死亡 0.36)

**GLORY / MECHA_KNIGHT_ELITE** (Elite; 怪物 MECHA_KNIGHT) — real / real-v3 / 构筑 `af4a578e3786`
- 牌组 33 张：ASCENDERS_BANE, BACKFLIP, BACKFLIP [NIMBLE 2], BLADE_DANCE×2, CALCULATED_GAMBLE×2, DEFEND_SILENT×4, DEFLECT [NIMBLE 2], DEFLECT+1 [NIMBLE 2], ESCAPE_PLAN [NIMBLE 2], FAN_OF_KNIVES, FOOTWORK×2, HAND_TRICK [NIMBLE 2], HAZE, HIDDEN_DAGGERS, KNIFE_TRAP, LEG_SWEEP [NIMBLE 2], NEUTRALIZE+1, REFLEX, STORM_OF_STEEL, STRIKE_SILENT×2, SURVIVOR, TACTICIAN, TOOLS_OF_THE_TRADE×2, UNTOUCHABLE, UP_MY_SLEEVE+1
- 遗物 13 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, FRESNEL_LENS, BAG_OF_MARBLES, KUSARIGAMA, BLOOD_VIAL, GLASS_EYE, KUNAI, UNCEASING_TOP, JUZU_BRACELET, WAR_HAMMER, ANCHOR, VAMBRACE
- 标签（4 个种子净掉血）：[16, 1, 26, 0] → 均值 **10.8**，组内 std 12.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 32.7 (+22.0, 死亡 0.10), repo_mlp 39.5 (+28.8, 死亡 0.09), rtdl_mlp 40.7 (+29.9, 死亡 0.17), rtdl_resnet 45.3 (+34.5, 死亡 0.20), set_transformer 55.8 (+45.0, 死亡 0.45), tabm 46.3 (+35.5, 死亡 0.24), ensemble 43.4 (+32.6, 死亡 0.21)

**GLORY / MECHA_KNIGHT_ELITE** (Elite; 怪物 MECHA_KNIGHT) — real / real-v3 / 构筑 `241edf1ae779`
- 牌组 32 张：ASCENDERS_BANE, BACKFLIP, BACKFLIP [NIMBLE 2], BLADE_DANCE×2, CALCULATED_GAMBLE×2, DEFEND_SILENT×4, DEFLECT [NIMBLE 2], ESCAPE_PLAN [NIMBLE 2], FAN_OF_KNIVES, FOOTWORK×2, HAND_TRICK [NIMBLE 2], HAZE, HIDDEN_DAGGERS, KNIFE_TRAP, LEG_SWEEP [NIMBLE 2], NEUTRALIZE+1, REFLEX, STORM_OF_STEEL, STRIKE_SILENT×2, SURVIVOR, TACTICIAN, TOOLS_OF_THE_TRADE×2, UNTOUCHABLE, UP_MY_SLEEVE+1
- 遗物 12 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, FRESNEL_LENS, BAG_OF_MARBLES, KUSARIGAMA, BLOOD_VIAL, GLASS_EYE, KUNAI, UNCEASING_TOP, JUZU_BRACELET, WAR_HAMMER, ANCHOR
- 标签（4 个种子净掉血）：[31, 27, 11, 4] → 均值 **18.2**，组内 std 12.8，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 36.6 (+18.3, 死亡 0.10), repo_mlp 38.3 (+20.0, 死亡 0.06), rtdl_mlp 45.2 (+26.9, 死亡 0.19), rtdl_resnet 56.3 (+38.0, 死亡 0.30), set_transformer 59.4 (+41.2, 死亡 0.52), tabm 49.8 (+31.5, 死亡 0.29), ensemble 47.6 (+29.3, 死亡 0.25)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — mutation / mut-v1 / 构筑 `670389899b0b`
- 牌组 29 张：ACCELERANT, ACCELERANT+1, ACROBATICS, ASCENDERS_BANE, CALCULATED_GAMBLE+1 [SOULS_POWER 1], CLOAK_AND_DAGGER+1, DEADLY_POISON+1×2, DECAY, DEFEND_SILENT×2, DEFEND_SILENT+1×3, EXPOSE, FAN_OF_KNIVES, FISTICUFFS, FOLLY, FOOTWORK+1, HIDDEN_DAGGERS, MIRAGE, POUNCE, RICOCHET+1 [SHARP 2], SNAKEBITE+1, STRIKE_SILENT+1, SUPPRESS+1, SURVIVOR+1, TACTICIAN+1, WELL_LAID_PLANS+1
- 遗物 24 件：RING_OF_THE_SNAKE, LEAD_PAPERWEIGHT, TINY_MAILBOX, WAR_PAINT, WHETSTONE, MERCURY_HOURGLASS, ARCHAIC_TOOTH, TOUGH_BANDAGES, SPARKLING_ROUGE, VAMBRACE, FESTIVE_POPPER, UNCEASING_TOP, PRESERVED_FOG, FAKE_MERCHANTS_RUG, FAKE_ORICHALCUM, FAKE_LEES_WAFFLE, FAKE_HAPPY_FLOWER(TurnsSeen=2), FAKE_VENERABLE_TEA_SET(GainEnergyInNextCombat=False), FAKE_STRIKE_DUMMY, MINIATURE_TENT, ODDLY_SMOOTH_STONE, PANTOGRAPH, CENTENNIAL_PUZZLE, VAJRA
- 变异：small / cards，改牌 1 改遗物 0，父代 `0fcd1c8d2ec4`
- 标签（4 个种子净掉血）：[30, 3, 16, 8] → 均值 **14.2**，组内 std 11.8，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 39.7 (+25.5, 死亡 0.10), repo_mlp 66.6 (+52.4, 死亡 0.80), rtdl_mlp 27.6 (+13.3, 死亡 0.01), rtdl_resnet 45.4 (+31.2, 死亡 0.40), set_transformer 53.2 (+38.9, 死亡 0.40), tabm 47.3 (+33.1, 死亡 0.30), ensemble 46.6 (+32.4, 死亡 0.34)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — real / real-v4 / 构筑 `4d00c5983461`
- 牌组 40 张：ABRASIVE+1, ACCURACY, ACROBATICS, AFTERIMAGE+1 [CLONE 4]×4, ASCENDERS_BANE, BACKFLIP+1, BACKSTAB, CALCULATED_GAMBLE, CLOAK_AND_DAGGER+1×2, CLUMSY, DAGGER_SPRAY, DEFEND_SILENT×5, DRAMATIC_ENTRANCE, DRAMATIC_ENTRANCE+1 [INSTINCT 1], ECHOING_SLASH [INSTINCT 1], ESCAPE_PLAN×2, GOLD_AXE [INSTINCT 1], HIDDEN_DAGGERS, LEADING_STRIKE×2, MAD_SCIENCE+1 {TinkerTimeRider=7,TinkerTimeType=3}, NEUTRALIZE, PHANTOM_BLADES+1, PIERCING_WAIL, PINPOINT+1, RICOCHET, SHADOW_STEP+1, SHOCKWAVE, STRIKE_SILENT×2, SURVIVOR
- 遗物 15 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, BAG_OF_MARBLES, WHETSTONE, CENTENNIAL_PUZZLE, POTION_BELT, PAELS_GROWTH, PENDULUM(TurnsSeen=2), TUNGSTEN_ROD, MEAL_TICKET, STRIKE_DUMMY, TRI_BOOMERANG, FORGOTTEN_SOUL, HAPPY_FLOWER(TurnsSeen=2), VENERABLE_TEA_SET(GainEnergyInNextCombat=True)
- 标签（4 个种子净掉血）：[2, 2, 19, 7] → 均值 **7.5**，组内 std 8.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 53.2 (+45.7, 死亡 0.28), repo_mlp 33.2 (+25.7, 死亡 0.03), rtdl_mlp 21.5 (+14.0, 死亡 0.00), rtdl_resnet 23.0 (+15.5, 死亡 0.01), set_transformer 45.9 (+38.4, 死亡 0.13), tabm 35.3 (+27.8, 死亡 0.12), ensemble 35.3 (+27.8, 死亡 0.10)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — real / real-v4 / 构筑 `6aeed3f902f1`
- 牌组 23 张：ACCURACY+1, ASCENDERS_BANE, ASSASSINATE+1, BACKFLIP+1, BLADE_DANCE, CLOAK_AND_DAGGER, DEFEND_SILENT, DEFEND_SILENT+1, DEFLECT, FOOTWORK+1, INFINITE_BLADES+1 [SWIFT 2], KNIFE_TRAP+1, LEG_SWEEP, NEUTRALIZE, PIERCING_WAIL, PREDATOR, PREPARED×2, PREPARED+1, STRIKE_SILENT+1, SURVIVOR+1, UP_MY_SLEEVE, UP_MY_SLEEVE [IMBUED 1]
- 遗物 14 件：RING_OF_THE_SNAKE, LARGE_CAPSULE, BRONZE_SCALES, JUZU_BRACELET, SWORD_OF_STONE(ElitesDefeated=1), WAR_PAINT, ELECTRIC_SHRYMP, DAUGHTER_OF_THE_WIND, MEAT_ON_THE_BONE, REGAL_PILLOW, MINIATURE_TENT, MEAT_CLEAVER, VAMBRACE, ORNAMENTAL_FAN
- 标签（4 个种子净掉血）：[7, 19, 23, 26] → 均值 **18.8**，组内 std 8.3，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 38.2 (+19.5, 死亡 0.21), repo_mlp 58.7 (+39.9, 死亡 0.70), rtdl_mlp 60.8 (+42.0, 死亡 0.78), rtdl_resnet 55.0 (+36.3, 死亡 0.50), set_transformer 57.0 (+38.3, 死亡 0.57), tabm 57.4 (+38.7, 死亡 0.55), ensemble 54.5 (+35.8, 死亡 0.55)

**OVERGROWTH / THE_KIN_BOSS** (Boss; 怪物 KIN_FOLLOWER, KIN_PRIEST) — real / real-v3 / 构筑 `c4776ed96fa5`
- 牌组 21 张：ACROBATICS, ASCENDERS_BANE, DEFEND_SILENT×4, DEFLECT, FLECHETTES+1, MEMENTO_MORI, NEUTRALIZE, NOXIOUS_FUMES, PIERCING_WAIL, PINPOINT, REFLEX, STRIKE_SILENT×2, SUCKER_PUNCH, SURVIVOR, UNTOUCHABLE×2, WELL_LAID_PLANS+1
- 遗物 3 件：RING_OF_THE_SNAKE, POTION_BELT, AMETHYST_AUBERGINE
- 标签（4 个种子净掉血）：[3, 23, 17, 21] → 均值 **16.0**，组内 std 9.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 54.8 (+38.8, 死亡 0.30), repo_mlp 53.6 (+37.6, 死亡 0.35), rtdl_mlp 55.2 (+39.2, 死亡 0.34), rtdl_resnet 57.1 (+41.1, 死亡 0.41), set_transformer 53.5 (+37.5, 死亡 0.24), tabm 56.5 (+40.5, 死亡 0.29), ensemble 55.1 (+39.1, 死亡 0.32)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — real / real-v4 / 构筑 `321364d41e0c`
- 牌组 32 张：ACROBATICS×2, ADRENALINE+1, AFTERIMAGE, ASCENDERS_BANE, BACKFLIP×2, DAGGER_SPRAY+1, DEFEND_SILENT×4, DEFEND_SILENT+1, ESCAPE_PLAN×2, EXPERTISE+1, EXPOSE, FLECHETTES+1, HIDDEN_DAGGERS, HIDDEN_DAGGERS+1, MAUL+1×2, NEUTRALIZE+1, PIERCING_WAIL, PREP_TIME, PROWESS+1, RICOCHET+1, SNAKEBITE, SURVIVOR, TACTICIAN+1×2, TOOLS_OF_THE_TRADE
- 遗物 18 件：RING_OF_THE_DRAKE, PRECARIOUS_SHEARS, MINIATURE_CANNON, RED_MASK, SHOVEL, GORGET, TOUCH_OF_OROBAS, VEXING_PUZZLEBOX, PERMAFROST, AMETHYST_AUBERGINE, MEAL_TICKET, JUZU_BRACELET, CLAWS, HISTORY_COURSE, INTIMIDATING_HELMET, PAPER_KRANE, WHETSTONE, POTION_BELT
- 标签（4 个种子净掉血）：[4, 6, 0, 23] → 均值 **8.2**，组内 std 10.1，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 50.9 (+42.6, 死亡 0.60), repo_mlp 25.9 (+17.6, 死亡 0.06), rtdl_mlp 31.1 (+22.9, 死亡 0.00), rtdl_resnet 40.3 (+32.1, 死亡 0.27), set_transformer 45.5 (+37.2, 死亡 0.17), tabm 52.0 (+43.8, 死亡 0.44), ensemble 40.9 (+32.7, 死亡 0.25)

## 最严重低估（预测 ≪ 标签）

模型认为安全，实际老师掉血多或死亡。

**GLORY / THE_LOST_AND_FORGOTTEN_NORMAL** (Monster; 怪物 THE_LOST, THE_FORGOTTEN) — real / real-v3 / 构筑 `b716d1505a8f`
- 牌组 31 张：ACROBATICS, ADRENALINE [SOULS_POWER 1], AFTERIMAGE+1, ASCENDERS_BANE, ASSASSINATE+1, CLOAK_AND_DAGGER×2, DECAY, DEFEND_SILENT×5, DODGE_AND_ROLL, EXPOSE, FAN_OF_KNIVES, FOOTWORK+1, HIDDEN_DAGGERS, INFINITE_BLADES+1, KNIFE_TRAP, LEG_SWEEP, STRIKE_SILENT×4, SUPPRESS+1, SURVIVOR, TORIC_TOUGHNESS, UNTOUCHABLE×2, UP_MY_SLEEVE
- 遗物 12 件：RING_OF_THE_SNAKE, HEFTY_TABLET, PLANISPHERE, PERMAFROST, JOSS_PAPER(CardsExhausted=2), ARCHAIC_TOOTH, GORGET, ODDLY_SMOOTH_STONE, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), BEATING_REMNANT, SNECKO_SKULL, IRON_CLUB(CardsPlayed=3)
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 11.2 (-58.8, 死亡 0.00), repo_mlp 7.5 (-62.5, 死亡 0.00), rtdl_mlp 7.0 (-63.0, 死亡 0.00), rtdl_resnet 20.9 (-49.1, 死亡 0.00), set_transformer 7.0 (-63.0, 死亡 0.00), tabm 7.6 (-62.4, 死亡 0.00), ensemble 10.2 (-59.8, 死亡 0.00)

**GLORY / THE_LOST_AND_FORGOTTEN_NORMAL** (Monster; 怪物 THE_LOST, THE_FORGOTTEN) — mutation / mut-v1 / 构筑 `3087d2feb079`
- 牌组 31 张：ACROBATICS, ADRENALINE [SOULS_POWER 1], ASCENDERS_BANE, ASSASSINATE+1, CLOAK_AND_DAGGER×2, DECAY, DEFEND_SILENT×5, DODGE_AND_ROLL, EXPERTISE, EXPOSE, FAN_OF_KNIVES, FOOTWORK+1, HIDDEN_DAGGERS, INFINITE_BLADES+1, KNIFE_TRAP, LEG_SWEEP, PREP_TIME+1, STRIKE_SILENT×4, SURVIVOR, TORIC_TOUGHNESS, UNTOUCHABLE×2, UP_MY_SLEEVE
- 遗物 12 件：RING_OF_THE_SNAKE, HEFTY_TABLET, PLANISPHERE, PERMAFROST, JOSS_PAPER(CardsExhausted=2), ARCHAIC_TOOTH, GORGET, ODDLY_SMOOTH_STONE, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), BEATING_REMNANT, SNECKO_SKULL, IRON_CLUB(CardsPlayed=3)
- 变异：small / cards，改牌 2 改遗物 0，父代 `b716d1505a8f`
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 12.6 (-57.4, 死亡 0.00), repo_mlp 10.0 (-60.0, 死亡 0.00), rtdl_mlp 12.6 (-57.4, 死亡 0.00), rtdl_resnet 24.2 (-45.8, 死亡 0.00), set_transformer 12.2 (-57.8, 死亡 0.00), tabm 13.2 (-56.8, 死亡 0.00), ensemble 14.1 (-55.9, 死亡 0.00)

**OVERGROWTH / PHROG_PARASITE_ELITE** (Elite; 怪物 PHROG_PARASITE, WRIGGLER) — real / real-v3 / 构筑 `85ee73ed6a1d`
- 牌组 13 张：ASCENDERS_BANE, DEFEND_SILENT×5, INFINITE_BLADES+1, LEADING_STRIKE×2, NEUTRALIZE+1, REFLEX, STRIKE_SILENT, SURVIVOR
- 遗物 4 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, MEAL_TICKET, BAG_OF_PREPARATION
- 标签（4 个种子净掉血）：[70, 51, 70, 70] → 均值 **65.2**，组内 std 9.5，死亡 3/4
- 预测（误差，死亡概率）：lightgbm 32.0 (-33.3, 死亡 0.19), repo_mlp 30.2 (-35.1, 死亡 0.02), rtdl_mlp 19.3 (-45.9, 死亡 0.00), rtdl_resnet 20.3 (-45.0, 死亡 0.00), set_transformer 14.4 (-50.9, 死亡 0.00), tabm 26.5 (-38.8, 死亡 0.04), ensemble 23.8 (-41.5, 死亡 0.04)

**OVERGROWTH / PHROG_PARASITE_ELITE** (Elite; 怪物 PHROG_PARASITE, WRIGGLER) — real / real-v3 / 构筑 `0068bdaca285`
- 牌组 14 张：ASCENDERS_BANE, BLUR+1, DEFEND_SILENT×5, INFINITE_BLADES+1, LEADING_STRIKE×2, NEUTRALIZE+1, REFLEX, STRIKE_SILENT, SURVIVOR
- 遗物 5 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, MEAL_TICKET, BAG_OF_PREPARATION, CENTENNIAL_PUZZLE
- 标签（4 个种子净掉血）：[70, 48, 52, 60] → 均值 **57.5**，组内 std 9.7，死亡 1/4
- 预测（误差，死亡概率）：lightgbm 28.7 (-28.8, 死亡 0.26), repo_mlp 31.9 (-25.6, 死亡 0.05), rtdl_mlp 16.8 (-40.7, 死亡 0.00), rtdl_resnet 13.1 (-44.4, 死亡 0.00), set_transformer 7.4 (-50.1, 死亡 0.00), tabm 23.7 (-33.8, 死亡 0.04), ensemble 20.3 (-37.2, 死亡 0.06)

**HIVE / MYTES_NORMAL** (Monster; 怪物 MYTE) — real / real-v4 / 构筑 `4499f0f0dd32`
- 牌组 16 张：ACCELERANT+1, ASCENDERS_BANE, CALCULATED_GAMBLE+1, DEFEND_SILENT×4, DEFEND_SILENT+1 [SPIRAL 1], LEG_SWEEP+1, NEUTRALIZE+1, STRIKE_SILENT×4, SUCKER_PUNCH+1, SURVIVOR+1
- 遗物 7 件：RING_OF_THE_SNAKE, NEW_LEAF, CAPTAINS_WHEEL, GORGET, AMETHYST_AUBERGINE, WAR_PAINT, PENDULUM(TurnsSeen=0)
- 标签（4 个种子净掉血）：[65, 34, 68, 70] → 均值 **59.2**，组内 std 17.0，死亡 1/4
- 预测（误差，死亡概率）：lightgbm 11.2 (-48.0, 死亡 0.00), repo_mlp 17.8 (-41.5, 死亡 0.00), rtdl_mlp 14.2 (-45.1, 死亡 0.00), rtdl_resnet 12.8 (-46.4, 死亡 0.00), set_transformer 11.0 (-48.3, 死亡 0.00), tabm 6.0 (-53.3, 死亡 0.00), ensemble 12.2 (-47.1, 死亡 0.00)

**UNDERDOCKS / LAGAVULIN_MATRIARCH_BOSS** (Boss; 怪物 LAGAVULIN_MATRIARCH) — real / real-v3 / 构筑 `3f3183e6f98a`
- 牌组 17 张：ACCURACY+1, ASCENDERS_BANE, BACKSTAB, CLOAK_AND_DAGGER+1, DEFEND_SILENT×4, DODGE_AND_ROLL, FLICK_FLACK, LEADING_STRIKE, NEUTRALIZE+1, STRIKE_SILENT×4, SURVIVOR
- 遗物 5 件：RING_OF_THE_SNAKE, LAVA_ROCK(HasTriggered=False), STONE_CRACKER, TUNING_FORK(SkillsPlayed=0), GORGET
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 42.6 (-27.4, 死亡 0.35), repo_mlp 45.3 (-24.7, 死亡 0.28), rtdl_mlp 58.3 (-11.7, 死亡 0.52), rtdl_resnet 41.0 (-29.0, 死亡 0.02), set_transformer 21.8 (-48.2, 死亡 0.00), tabm 53.9 (-16.1, 死亡 0.39), ensemble 43.8 (-26.2, 死亡 0.26)

**UNDERDOCKS / LAGAVULIN_MATRIARCH_BOSS** (Boss; 怪物 LAGAVULIN_MATRIARCH) — real / real-v3 / 构筑 `ddef06c2cd41`
- 牌组 19 张：ACROBATICS, ADRENALINE+1, ASCENDERS_BANE, BACKFLIP [NIMBLE 2], DEFEND_SILENT×5, INFINITE_BLADES [SWIFT 2], NEUTRALIZE, PINPOINT, SPEEDSTER+1, STRIKE_SILENT×5, SURVIVOR
- 遗物 7 件：RING_OF_THE_SNAKE, ARCANE_SCROLL, FRESNEL_LENS, NUNCHAKU(AttacksPlayed=9), VAJRA, BEATING_REMNANT, JOSS_PAPER(CardsExhausted=3)
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 62.6 (-7.4, 死亡 0.52), repo_mlp 36.3 (-33.7, 死亡 0.09), rtdl_mlp 61.3 (-8.7, 死亡 0.51), rtdl_resnet 55.8 (-14.2, 死亡 0.44), set_transformer 28.2 (-41.8, 死亡 0.01), tabm 46.3 (-23.7, 死亡 0.24), ensemble 48.4 (-21.6, 死亡 0.30)

**HIVE / ENTOMANCER_ELITE** (Elite; 怪物 ENTOMANCER) — real / real-v4 / 构筑 `eb63aae37593`
- 牌组 20 张：ASCENDERS_BANE, BLADE_DANCE, CLOAK_AND_DAGGER+1, DEFEND_SILENT×5, GREED, LANTERN_KEY, LEG_SWEEP, POISONED_STAB+1, PREPARED+1, REFLEX, SHADOWMELD, STRIKE_SILENT×2, SUPPRESS+1, SURVIVOR [NIMBLE 2], UNTOUCHABLE+1
- 遗物 8 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, KUSARIGAMA, HAPPY_FLOWER(TurnsSeen=1), SHURIKEN, AMETHYST_AUBERGINE, ARCHAIC_TOOTH, REGAL_PILLOW
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 25.3 (-44.7, 死亡 0.05), repo_mlp 31.5 (-38.5, 死亡 0.02), rtdl_mlp 30.6 (-39.4, 死亡 0.04), rtdl_resnet 28.8 (-41.2, 死亡 0.01), set_transformer 28.6 (-41.4, 死亡 0.01), tabm 30.2 (-39.8, 死亡 0.03), ensemble 29.2 (-40.8, 死亡 0.03)

## 高掉血但预测准确

标签均值 ≥ 25 HP 且 |误差| ≤ 2 HP 的 pair。

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — real / real-v3 / 构筑 `be48f07dada4`
- 牌组 35 张：ACCELERANT+1×2, ACROBATICS, ASCENDERS_BANE, BACKFLIP, BLUR+1, CALCULATED_GAMBLE, CLUMSY, DEFEND_SILENT×5, DEFLECT, DODGE_AND_ROLL, ECHOING_SLASH+1 [VIGOROUS 8], ESCAPE_PLAN, FINESSE+1, FOOTWORK, FOOTWORK+1×2, MIRAGE, NEUTRALIZE+1, NIGHTMARE [IMBUED 1], NOXIOUS_FUMES+1×2, PIERCING_WAIL×2, SHAME, SLICE, SNAKEBITE+1, STRIKE_SILENT×3, SURVIVOR
- 遗物 17 件：RING_OF_THE_SNAKE, NEW_LEAF, ANCHOR, CENTENNIAL_PUZZLE, PENDULUM(TurnsSeen=0), LASTING_CANDY(CombatRewardsSeen=2), ELECTRIC_SHRYMP, GORGET, THE_COURIER, HAPPY_FLOWER(TurnsSeen=0), BEATING_REMNANT, PHILOSOPHERS_STONE, DOLLYS_MIRROR, RED_MASK, BRONZE_SCALES, TINGSHA, POTION_BELT
- 标签（4 个种子净掉血）：[58, 70, 70, 45] → 均值 **60.8**，组内 std 11.9，死亡 2/4
- 预测（误差，死亡概率）：lightgbm 48.7 (-12.1, 死亡 0.56), repo_mlp 39.2 (-21.6, 死亡 0.06), rtdl_mlp 52.1 (-8.6, 死亡 0.44), rtdl_resnet 57.1 (-3.7, 死亡 0.53), set_transformer 61.8 (+1.0, 死亡 0.61), tabm 55.2 (-5.5, 死亡 0.48), ensemble 52.3 (-8.4, 死亡 0.44)

**HIVE / INFESTED_PRISMS_ELITE** (Elite; 怪物 INFESTED_PRISM) — real / real-v3 / 构筑 `a13d6ac4da25`
- 牌组 23 张：ASCENDERS_BANE, BLADE_DANCE+1, BOUNCING_FLASK+1, CLOAK_AND_DAGGER+1, DEADLY_POISON, DEFEND_SILENT×4, ESCAPE_PLAN, INFINITE_BLADES, LEADING_STRIKE, NEUTRALIZE, NORMALITY, OUTBREAK+1, PHANTOM_BLADES+1, PREPARED+1, SNAKEBITE+1, STRIKE_SILENT×2, SURVIVOR [NIMBLE 2], TACTICIAN, TACTICIAN+1
- 遗物 9 件：RING_OF_THE_SNAKE, NEOWS_BONES, SILVER_CRUCIBLE(TimesUsed=1,TreasureRoomsEntered=2), PRECARIOUS_SHEARS, CLOAK_CLASP, SNECKO_SKULL, AKABEKO, SEAL_OF_GOLD, NUNCHAKU(AttacksPlayed=2)
- 标签（4 个种子净掉血）：[32, 31, 55, 30] → 均值 **37.0**，组内 std 12.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 36.2 (-0.8, 死亡 0.00), repo_mlp 30.9 (-6.1, 死亡 0.00), rtdl_mlp 23.8 (-13.2, 死亡 0.00), rtdl_resnet 34.3 (-2.7, 死亡 0.00), set_transformer 35.6 (-1.4, 死亡 0.00), tabm 35.9 (-1.1, 死亡 0.02), ensemble 32.8 (-4.2, 死亡 0.00)

**HIVE / KAISER_CRAB_BOSS** (Boss; 怪物 CRUSHER, ROCKET) — real / real-v3 / 构筑 `7559dec42cf8`
- 牌组 24 张：ASCENDERS_BANE, BLADE_DANCE+1, BRIGHTEST_FLAME, CALCULATED_GAMBLE, DAGGER_SPRAY, DEFEND_SILENT×3, DEFEND_SILENT+1×2, INFINITE_BLADES×2, NEUTRALIZE, PIERCING_WAIL+1, PINPOINT+1, PREPARED, REND, SERPENT_FORM, SIDESTEP, SNAKEBITE, STRIKE_SILENT×3, SURVIVOR
- 遗物 10 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, FESTIVE_POPPER, STRIKE_DUMMY, STORYBOOK, PENDULUM(TurnsSeen=2), BAG_OF_MARBLES, GREMLIN_HORN, TUNING_FORK(SkillsPlayed=5), WAR_PAINT
- 标签（4 个种子净掉血）：[70, 70, 57, 51] → 均值 **62.0**，组内 std 9.6，死亡 2/4
- 预测（误差，死亡概率）：lightgbm 56.4 (-5.6, 死亡 0.11), repo_mlp 70.0 (+8.0, 死亡 0.50), rtdl_mlp 66.8 (+4.8, 死亡 0.73), rtdl_resnet 69.2 (+7.2, 死亡 0.79), set_transformer 63.5 (+1.5, 死亡 0.47), tabm 65.6 (+3.6, 死亡 0.58), ensemble 65.3 (+3.3, 死亡 0.53)

**HIVE / THE_INSATIABLE_BOSS** (Boss; 怪物 THE_INSATIABLE) — real / real-v3 / 构筑 `77db67890184`
- 牌组 27 张：ASCENDERS_BANE, BACKFLIP, BUBBLE_BUBBLE, CALCULATED_GAMBLE+1, CLOAK_AND_DAGGER, DEFEND_SILENT×4, DEFLECT, ESCAPE_PLAN, FLICK_FLACK, FOOTWORK, HAND_TRICK, LEADING_STRIKE+1, NEUTRALIZE+1, PREPARED, PREPARED+1, REFLEX+1, RICOCHET, SIDESTEP, SNAKEBITE, STRIKE_SILENT, STRIKE_SILENT+1, SURVIVOR+1, TACTICIAN, WELL_LAID_PLANS
- 遗物 12 件：RING_OF_THE_SNAKE, SCROLL_BOXES, SPARKLING_ROUGE, OLD_COIN, POTION_BELT, RINGING_TRIANGLE, WAR_PAINT, AMETHYST_AUBERGINE, TOASTY_MITTENS, UNSETTLING_LAMP, PENDULUM(TurnsSeen=2), WHETSTONE
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 59.2 (-10.8, 死亡 0.58), repo_mlp 57.0 (-13.0, 死亡 0.70), rtdl_mlp 58.0 (-12.0, 死亡 0.66), rtdl_resnet 54.2 (-15.8, 死亡 0.53), set_transformer 68.3 (-1.7, 死亡 0.94), tabm 60.2 (-9.8, 死亡 0.63), ensemble 59.5 (-10.5, 死亡 0.67)

**OVERGROWTH / BYGONE_EFFIGY_ELITE** (Elite; 怪物 BYGONE_EFFIGY) — real / real-v3 / 构筑 `85c36081b0ef`
- 牌组 15 张：ASCENDERS_BANE, DEFEND_SILENT×5, ECHOING_SLASH+1, LEADING_STRIKE×2, NEUTRALIZE, RICOCHET, STRIKE_SILENT×3, SURVIVOR
- 遗物 3 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, BRONZE_SCALES
- 标签（4 个种子净掉血）：[20, 35, 43, 35] → 均值 **33.2**，组内 std 9.6，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 39.0 (+5.8, 死亡 0.00), repo_mlp 25.4 (-7.8, 死亡 0.00), rtdl_mlp 28.3 (-5.0, 死亡 0.00), rtdl_resnet 32.4 (-0.9, 死亡 0.00), set_transformer 32.1 (-1.2, 死亡 0.00), tabm 24.5 (-8.8, 死亡 0.00), ensemble 30.3 (-3.0, 死亡 0.00)

**OVERGROWTH / BYRDONIS_ELITE** (Elite; 怪物 BYRDONIS) — real / real-v3 / 构筑 `f52a75ede3cb`
- 牌组 17 张：ACCELERANT, ASCENDERS_BANE, DEFEND_SILENT×5, FOOTWORK [SWIFT 2], LEADING_STRIKE, NEUTRALIZE, NOXIOUS_FUMES+1, PIERCING_WAIL, POOR_SLEEP, STRIKE_SILENT×3, SURVIVOR
- 遗物 2 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS
- 标签（4 个种子净掉血）：[38, 23, 24, 22] → 均值 **26.8**，组内 std 7.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 31.0 (+4.3, 死亡 0.00), repo_mlp 26.0 (-0.8, 死亡 0.00), rtdl_mlp 25.8 (-1.0, 死亡 0.00), rtdl_resnet 24.6 (-2.1, 死亡 0.00), set_transformer 27.2 (+0.5, 死亡 0.00), tabm 24.1 (-2.6, 死亡 0.00), ensemble 26.5 (-0.3, 死亡 0.00)

**UNDERDOCKS / LAGAVULIN_MATRIARCH_BOSS** (Boss; 怪物 LAGAVULIN_MATRIARCH) — real / real-v3 / 构筑 `84a06116f095`
- 牌组 19 张：ASCENDERS_BANE, BOUNCING_FLASK, DEFEND_SILENT×4, DEFEND_SILENT+1, ESCAPE_PLAN+1, LEADING_STRIKE×2, NEUTRALIZE+1, PIERCING_WAIL, RIP_AND_TEAR, SNAKEBITE+1, STRIKE_SILENT×4, SURVIVOR
- 遗物 8 件：RING_OF_THE_SNAKE, LAVA_ROCK(HasTriggered=False), FRESNEL_LENS, TUNING_FORK(SkillsPlayed=9), ORICHALCUM, WAR_PAINT, BLOOD_VIAL, RED_MASK
- 标签（4 个种子净掉血）：[67, 28, 39, 29] → 均值 **40.8**，组内 std 18.2，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 29.7 (-11.0, 死亡 0.07), repo_mlp 30.5 (-10.3, 死亡 0.02), rtdl_mlp 39.3 (-1.4, 死亡 0.21), rtdl_resnet 35.5 (-5.2, 死亡 0.00), set_transformer 40.9 (+0.2, 死亡 0.08), tabm 29.5 (-11.2, 死亡 0.04), ensemble 34.3 (-6.5, 死亡 0.07)

**UNDERDOCKS / SKULKING_COLONY_ELITE** (Elite; 怪物 SKULKING_COLONY) — real / real-v3 / 构筑 `c46d95fa2724`
- 牌组 18 张：ASCENDERS_BANE, DEFEND_SILENT×4, DEFEND_SILENT+1, FLICK_FLACK×2, GREED, NEUTRALIZE, POISONED_STAB, ROLLING_BOULDER, STORM_OF_STEEL, STRIKE_SILENT×4, SURVIVOR
- 遗物 3 件：RING_OF_THE_SNAKE, ARCANE_SCROLL, MEAL_TICKET
- 标签（4 个种子净掉血）：[40, 30, 24, 42] → 均值 **34.0**，组内 std 8.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 22.4 (-11.6, 死亡 0.00), repo_mlp 29.2 (-4.8, 死亡 0.00), rtdl_mlp 25.5 (-8.5, 死亡 0.00), rtdl_resnet 25.6 (-8.4, 死亡 0.00), set_transformer 32.0 (-2.0, 死亡 0.00), tabm 27.4 (-6.6, 死亡 0.00), ensemble 27.0 (-7.0, 死亡 0.00)

## 随机典型样例

无筛选随机抽取，反映一般水平。

**OVERGROWTH / VANTOM_BOSS** (Boss; 怪物 VANTOM) — real / real-v3 / 构筑 `237bd36283e8`
- 牌组 16 张：ASCENDERS_BANE, DAGGER_SPRAY+1, DEFEND_SILENT×5, DEFLECT, FLECHETTES+1, NEUTRALIZE+1, RICOCHET, STRIKE_SILENT×3, SURVIVOR, TORIC_TOUGHNESS+1
- 遗物 4 件：RING_OF_THE_SNAKE, STRIKE_DUMMY, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), TUNING_FORK(SkillsPlayed=7)
- 标签（4 个种子净掉血）：[70, 68, 38, 69] → 均值 **61.2**，组内 std 15.5，死亡 1/4
- 预测（误差，死亡概率）：lightgbm 42.2 (-19.0, 死亡 0.11), repo_mlp 43.7 (-17.6, 死亡 0.06), rtdl_mlp 45.9 (-15.4, 死亡 0.11), rtdl_resnet 50.9 (-10.4, 死亡 0.18), set_transformer 46.4 (-14.9, 死亡 0.07), tabm 48.8 (-12.4, 死亡 0.17), ensemble 46.3 (-14.9, 死亡 0.12)

**OVERGROWTH / RUBY_RAIDERS_NORMAL** (Monster; 怪物 AXE_RUBY_RAIDER, ASSASSIN_RUBY_RAIDER, BRUTE_RUBY_RAIDER, CROSSBOW_RUBY_RAIDER, TRACKER_RUBY_RAIDER) — real / real-v3 / 构筑 `faf5f5eec7b4`
- 牌组 18 张：ACCELERANT, ASCENDERS_BANE, DEFEND_SILENT×5, FOOTWORK [SWIFT 2], LEADING_STRIKE, NEUTRALIZE, NOXIOUS_FUMES+1, PIERCING_WAIL, POOR_SLEEP, STRIKE_SILENT×3, SURVIVOR, TOOLS_OF_THE_TRADE
- 遗物 4 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, MEAL_TICKET, BOOK_OF_FIVE_RINGS(CardsAdded=4)
- 标签（4 个种子净掉血）：[18, 20, 27, 12] → 均值 **19.2**，组内 std 6.2，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 16.7 (-2.6, 死亡 0.00), repo_mlp 12.4 (-6.8, 死亡 0.00), rtdl_mlp 14.2 (-5.0, 死亡 0.00), rtdl_resnet 15.6 (-3.7, 死亡 0.00), set_transformer 15.7 (-3.6, 死亡 0.00), tabm 15.1 (-4.2, 死亡 0.00), ensemble 14.9 (-4.3, 死亡 0.00)

**OVERGROWTH / SLIMES_WEAK** (Monster, weak; 怪物 LEAF_SLIME_S, TWIG_SLIME_S, LEAF_SLIME_M, TWIG_SLIME_M) — real / real-v3 / 构筑 `a34f2b1efb75`
- 牌组 13 张：ASCENDERS_BANE, DEFEND_SILENT×4, NEUTRALIZE, PRECISE_CUT, RICOCHET, STRIKE_SILENT×4, SURVIVOR
- 遗物 1 件：RING_OF_THE_SNAKE
- 标签（4 个种子净掉血）：[2, 0, 3, 1] → 均值 **1.5**，组内 std 1.3，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 1.1 (-0.4, 死亡 0.00), repo_mlp 0.1 (-1.4, 死亡 0.00), rtdl_mlp 1.7 (+0.2, 死亡 0.00), rtdl_resnet 1.5 (-0.0, 死亡 0.00), set_transformer 1.7 (+0.2, 死亡 0.00), tabm 0.8 (-0.7, 死亡 0.00), ensemble 1.1 (-0.4, 死亡 0.00)

**UNDERDOCKS / TERROR_EEL_ELITE** (Elite; 怪物 TERROR_EEL) — real / real-v3 / 构筑 `6a4c3b462018`
- 牌组 22 张：ASCENDERS_BANE, BACKSTAB, CALCULATED_GAMBLE+1, DASH×2, DEFEND_SILENT×5, EXPOSE, HAND_TRICK, MEMENTO_MORI, NEUTRALIZE, PREPARED, REFLEX, STRIKE_SILENT×5, SURVIVOR
- 遗物 5 件：RING_OF_THE_SNAKE, LAVA_ROCK(HasTriggered=False), ORRERY, TWISTED_FUNNEL, REGAL_PILLOW
- 标签（4 个种子净掉血）：[31, 28, 25, 31] → 均值 **28.8**，组内 std 2.9，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 26.6 (-2.1, 死亡 0.02), repo_mlp 32.9 (+4.1, 死亡 0.01), rtdl_mlp 35.5 (+6.8, 死亡 0.02), rtdl_resnet 30.7 (+1.9, 死亡 0.00), set_transformer 24.0 (-4.7, 死亡 0.00), tabm 23.5 (-5.3, 死亡 0.00), ensemble 28.9 (+0.1, 死亡 0.01)

**HIVE / SPINY_TOAD_NORMAL** (Monster; 怪物 SPINY_TOAD) — real / real-v3 / 构筑 `8599d3f9f6e1`
- 牌组 28 张：ACCURACY+1, ASCENDERS_BANE, ASSASSINATE, BACKFLIP×2, BLADE_DANCE, BLUR, CALCULATED_GAMBLE, CLOAK_AND_DAGGER, DEFEND_SILENT×5, DUAL_WIELD, FISTICUFFS, HAZE, INFINITE_BLADES, LEADING_STRIKE, PANACHE, PHANTOM_BLADES, STRIKE_SILENT×5, SUPPRESS+1, SURVIVOR
- 遗物 7 件：RING_OF_THE_SNAKE, LEAD_PAPERWEIGHT, SPARKLING_ROUGE, ANCHOR, HORN_CLEAT, MINIATURE_TENT, ARCHAIC_TOOTH
- 标签（4 个种子净掉血）：[0, 0, 0, 0] → 均值 **0.0**，组内 std 0.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 4.2 (+4.2, 死亡 0.00), repo_mlp 1.6 (+1.6, 死亡 0.00), rtdl_mlp 2.2 (+2.2, 死亡 0.00), rtdl_resnet 1.3 (+1.3, 死亡 0.00), set_transformer 2.3 (+2.3, 死亡 0.00), tabm 3.1 (+3.1, 死亡 0.00), ensemble 2.4 (+2.4, 死亡 0.00)

**UNDERDOCKS / SEWER_CLAM_NORMAL** (Monster; 怪物 SEWER_CLAM) — real / real-v3 / 构筑 `e3d69ce5929a`
- 牌组 20 张：ACCURACY, ASCENDERS_BANE, BLADE_DANCE, CLOAK_AND_DAGGER×2, DEFEND_SILENT×5, HAND_TRICK, NEUTRALIZE, PIERCING_WAIL, SNAKEBITE, STRIKE_SILENT×5, SURVIVOR
- 遗物 2 件：RING_OF_THE_SNAKE, SCROLL_BOXES
- 标签（4 个种子净掉血）：[5, 1, 2, 10] → 均值 **4.5**，组内 std 4.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 7.9 (+3.4, 死亡 0.00), repo_mlp 6.8 (+2.3, 死亡 0.00), rtdl_mlp 5.9 (+1.4, 死亡 0.00), rtdl_resnet 2.6 (-1.9, 死亡 0.00), set_transformer 3.7 (-0.8, 死亡 0.00), tabm 4.1 (-0.4, 死亡 0.00), ensemble 5.2 (+0.7, 死亡 0.00)

**HIVE / LOUSE_PROGENITOR_NORMAL** (Monster; 怪物 LOUSE_PROGENITOR) — real / real-v3 / 构筑 `982ae7152746`
- 牌组 25 张：ABRASIVE, ACCURACY+1, ANTICIPATE+1, ASCENDERS_BANE, BACKFLIP, BRIGHTEST_FLAME, CLOAK_AND_DAGGER, DEADLY_POISON, DEADLY_POISON+1, DEFEND_SILENT×4, HIDDEN_DAGGERS, LEADING_STRIKE, LEG_SWEEP, NEUTRALIZE, PREDATOR, SNAKEBITE, STRIKE_SILENT×4, SURVIVOR, TRACKING
- 遗物 6 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, CAPTAINS_WHEEL, UNSETTLING_LAMP, PANTOGRAPH, STORYBOOK
- 标签（4 个种子净掉血）：[15, 14, 2, 2] → 均值 **8.2**，组内 std 7.2，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 13.8 (+5.5, 死亡 0.00), repo_mlp 8.7 (+0.5, 死亡 0.00), rtdl_mlp 15.6 (+7.3, 死亡 0.00), rtdl_resnet 12.4 (+4.2, 死亡 0.00), set_transformer 9.4 (+1.2, 死亡 0.00), tabm 11.2 (+3.0, 死亡 0.00), ensemble 11.9 (+3.6, 死亡 0.00)

**HIVE / EXOSKELETONS_WEAK** (Monster, weak; 怪物 EXOSKELETON) — mutation / mut-v1 / 构筑 `16a9ed20b02d`
- 牌组 21 张：ABRASIVE+1, AFTERIMAGE [CLONE 4], ASCENDERS_BANE, CALCULATED_GAMBLE, CLOAK_AND_DAGGER+1, CLUMSY, DAGGER_SPRAY, DEFEND_SILENT×5, DRAMATIC_ENTRANCE+1, ESCAPE_PLAN, NEUTRALIZE, PIERCING_WAIL, PINPOINT+1, STRIKE_SILENT×3, SURVIVOR
- 遗物 5 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, CENTENNIAL_PUZZLE, POTION_BELT, PAELS_GROWTH
- 变异：small / both，改牌 1 改遗物 2，父代 `312db531e365`
- 标签（4 个种子净掉血）：[1, 0, 0, 2] → 均值 **0.8**，组内 std 1.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 2.9 (+2.1, 死亡 0.00), repo_mlp 2.7 (+1.9, 死亡 0.00), rtdl_mlp 3.5 (+2.7, 死亡 0.00), rtdl_resnet 1.7 (+0.9, 死亡 0.00), set_transformer 0.8 (+0.0, 死亡 0.00), tabm 2.1 (+1.3, 死亡 0.00), ensemble 2.3 (+1.5, 死亡 0.00)

