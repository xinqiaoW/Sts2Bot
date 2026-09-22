# 预测样例与误差分析

快照 `data/train-snapshots/20260915-113849`，测试集 74926 场 / 18733 对。主模型 **set_transformer**（pair MAE 3.95 HP，中位数 2.15，偏差 -0.45）。对比模型：lightgbm, repo_mlp, rtdl_mlp, rtdl_resnet, set_transformer, tabm, ensemble。误差 = 预测 − 同输入全部种子的均值，单位 HP。

## 误差分布（主模型，pair 级）

| 分位 | 25% | 50% | 75% | 90% | 95% | 99% |
|---|---|---|---|---|---|---|
| |误差| | 0.82 | 2.15 | 5.08 | 9.94 | 13.89 | 23.95 |

|误差| ≤ 2 HP 的 pair 占 47.7%，≤ 5 HP 占 74.7%，> 15 HP 占 4.2%。

注意“标签”本身是 4 个种子的均值，也带噪声：按组内 std/√n 估计，即使模型给出真实期望值，与 4 种子均值之间的 MAE 也约为 **2.41 HP**（正态近似 √(2/π)·std/√n 的平均）。因此主模型 pair MAE 3.95 中相当一部分来自标签噪声，而非模型误差。同理，“按标签均值分桶”中高标签桶的负偏差有一部分是选择效应（标签均值偶然偏高的 pair 被选进高桶），应以“按预测值分桶”判断校准。

## 校准：按预测值分桶

每桶给出 pair 数、平均预测、平均标签均值、偏差、MAE。理想情况下平均预测 ≈ 平均标签。

| 预测区间 | pairs | 平均预测 | 平均标签 | 偏差 | MAE |
|---|---|---|---|---|---|
| [0.0, 5.0) | 8143 | 2.10 | 2.52 | -0.42 | 1.52 |
| [5.0, 10.0) | 3122 | 7.24 | 7.77 | -0.53 | 3.61 |
| [10.0, 15.0) | 1951 | 12.34 | 12.80 | -0.46 | 4.62 |
| [15.0, 20.0) | 1359 | 17.38 | 18.24 | -0.85 | 5.91 |
| [20.0, 30.0) | 1579 | 24.61 | 25.39 | -0.79 | 7.32 |
| [30.0, 40.0) | 965 | 34.45 | 35.11 | -0.67 | 9.07 |
| [40.0, 50.0) | 619 | 44.88 | 45.41 | -0.53 | 9.83 |
| [50.0, 60.0) | 482 | 54.68 | 53.64 | 1.04 | 9.08 |
| [60.0, 70.01) | 513 | 65.80 | 64.90 | 0.90 | 4.77 |

## 校准：按标签均值分桶

看模型在高掉血/死亡输入上是否系统性低估（向均值回归）。

| 标签区间 | pairs | 平均标签 | 平均预测 | 偏差 | MAE | 组内 std |
|---|---|---|---|---|---|---|
| [0.0, 5.0) | 8066 | 1.80 | 2.79 | 0.99 | 1.70 | 2.23 |
| [5.0, 10.0) | 3095 | 7.09 | 7.56 | 0.47 | 3.32 | 5.89 |
| [10.0, 15.0) | 1897 | 12.16 | 12.02 | -0.14 | 4.26 | 7.86 |
| [15.0, 20.0) | 1278 | 17.24 | 16.69 | -0.55 | 5.27 | 9.14 |
| [20.0, 30.0) | 1607 | 24.37 | 22.77 | -1.61 | 6.73 | 10.98 |
| [30.0, 40.0) | 988 | 34.50 | 31.57 | -2.94 | 8.19 | 12.96 |
| [40.0, 50.0) | 631 | 44.72 | 39.95 | -4.77 | 9.49 | 15.31 |
| [50.0, 60.0) | 463 | 54.67 | 48.13 | -6.54 | 9.65 | 14.88 |
| [60.0, 70.01) | 708 | 66.97 | 59.43 | -7.54 | 8.17 | 4.56 |

## 死亡概率校准（row 级）

| 预测死亡概率 | rows | 平均预测 | 实际死亡率 |
|---|---|---|---|
| [0.0, 0.02) | 66940 | 0.00 | 0.00 |
| [0.02, 0.05) | 1864 | 0.03 | 0.08 |
| [0.05, 0.1) | 1084 | 0.07 | 0.11 |
| [0.1, 0.2) | 1200 | 0.15 | 0.21 |
| [0.2, 0.4) | 1288 | 0.29 | 0.32 |
| [0.4, 0.6) | 848 | 0.50 | 0.50 |
| [0.6, 0.8) | 798 | 0.70 | 0.68 |
| [0.8, 1.01) | 904 | 0.90 | 0.89 |

含死亡的 pair 1259 个（6.7%），其 pair MAE 8.84，偏差 -6.04；无死亡 pair MAE 3.59。全部种子死亡的 pair 287 个，平均预测 63.8 HP。

## 按怪物编组（主模型，pair 级）

按 MAE 从高到低；`弱` 为 weak 编组。

| 幕 | 编组 | 类型 | pairs | 平均标签 | 组内 std | 偏差 | MAE | 死亡场/总场 |
|---|---|---|---|---|---|---|---|---|
| GLORY | TEST_SUBJECT_BOSS | Boss | 206 | 46.16 | 14.18 | 2.78 | 10.68 | 291/824 |
| GLORY | QUEEN_BOSS | Boss | 223 | 47.64 | 11.55 | 0.61 | 10.35 | 291/890 |
| HIVE | THE_INSATIABLE_BOSS | Boss | 146 | 44.39 | 13.66 | -1.50 | 10.02 | 206/584 |
| GLORY | KNIGHTS_ELITE | Elite | 348 | 22.61 | 12.60 | -1.11 | 9.70 | 90/1392 |
| HIVE | KNOWLEDGE_DEMON_BOSS | Boss | 131 | 47.34 | 11.97 | -2.52 | 8.65 | 199/524 |
| UNDERDOCKS | SOUL_FYSH_BOSS | Boss | 89 | 38.25 | 9.58 | -2.55 | 8.57 | 55/356 |
| GLORY | AEONGLASS_BOSS | Boss | 203 | 52.75 | 11.51 | -2.17 | 8.51 | 437/812 |
| HIVE | KAISER_CRAB_BOSS | Boss | 105 | 47.90 | 10.84 | 1.63 | 8.00 | 115/420 |
| GLORY | MECHA_KNIGHT_ELITE | Elite | 275 | 25.10 | 12.94 | -1.47 | 7.92 | 40/1100 |
| OVERGROWTH | THE_KIN_BOSS | Boss | 125 | 42.29 | 8.77 | 4.53 | 7.88 | 108/500 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | Boss | 93 | 45.87 | 8.47 | -3.24 | 7.86 | 148/372 |
| GLORY | AXEBOTS_NORMAL | Monster | 179 | 14.68 | 9.82 | -1.70 | 7.58 | 8/716 |
| OVERGROWTH | VANTOM_BOSS | Boss | 132 | 36.49 | 9.40 | -2.28 | 7.21 | 59/528 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | Boss | 130 | 37.84 | 9.22 | -2.48 | 7.04 | 82/519 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | Boss | 95 | 42.82 | 9.49 | -1.65 | 6.94 | 60/380 |
| HIVE | INFESTED_PRISMS_ELITE | Elite | 415 | 23.60 | 7.75 | -0.20 | 6.58 | 25/1660 |
| HIVE | ENTOMANCER_ELITE | Elite | 406 | 21.54 | 9.70 | 0.43 | 6.42 | 107/1624 |
| HIVE | DECIMILLIPEDE_ELITE | Elite | 398 | 27.44 | 10.31 | -0.27 | 6.28 | 79/1592 |
| GLORY | CONSTRUCT_MENAGERIE_NORMAL | Monster | 113 | 16.81 | 10.06 | -2.66 | 5.79 | 0/452 |
| UNDERDOCKS | PHANTASMAL_GARDENERS_ELITE | Elite | 326 | 27.16 | 8.41 | -2.31 | 5.70 | 120/1304 |
| GLORY | THE_LOST_AND_FORGOTTEN_NORMAL | Monster | 170 | 10.82 | 8.40 | 1.32 | 5.65 | 9/680 |
| UNDERDOCKS | CULTISTS_NORMAL | Monster | 146 | 17.91 | 8.77 | -1.03 | 5.55 | 24/584 |
| OVERGROWTH | PHROG_PARASITE_ELITE | Elite | 441 | 22.09 | 8.89 | -0.29 | 5.44 | 168/1764 |
| OVERGROWTH | BYGONE_EFFIGY_ELITE | Elite | 436 | 24.40 | 7.88 | -1.23 | 5.42 | 37/1744 |
| HIVE | SLUMBERING_BEETLE_NORMAL | Monster | 187 | 16.10 | 9.06 | 0.33 | 5.37 | 19/748 |
| GLORY | SOUL_NEXUS_ELITE | Elite | 278 | 14.54 | 8.44 | -0.31 | 5.34 | 3/1112 |
| HIVE | OVICOPTER_NORMAL | Monster | 218 | 10.79 | 7.58 | -0.82 | 5.29 | 9/872 |
| UNDERDOCKS | TERROR_EEL_ELITE | Elite | 299 | 24.27 | 7.33 | -1.45 | 4.74 | 29/1196 |
| GLORY | SCROLLS_OF_BITING_NORMAL | Monster | 192 | 6.17 | 5.83 | 2.01 | 4.58 | 0/768 |
| HIVE | THE_OBSCURA_NORMAL | Monster | 206 | 7.70 | 6.76 | 2.21 | 4.57 | 0/824 |
| GLORY | FABRICATOR_NORMAL | Monster | 150 | 7.89 | 7.60 | -1.21 | 4.48 | 0/598 |
| GLORY | FROG_KNIGHT_NORMAL | Monster | 143 | 8.18 | 5.56 | -1.49 | 4.42 | 0/572 |
| OVERGROWTH | BYRDONIS_ELITE | Elite | 482 | 23.16 | 6.64 | -1.27 | 4.37 | 17/1928 |
| GLORY | DEVOTED_SCULPTOR_WEAK | Monster弱 | 441 | 6.83 | 5.67 | -1.43 | 4.10 | 3/1764 |
| HIVE | MYTES_NORMAL | Monster | 230 | 10.17 | 6.20 | -1.87 | 4.05 | 1/920 |
| GLORY | SLIMED_BERSERKER_NORMAL | Monster | 182 | 8.07 | 6.43 | -1.20 | 3.91 | 3/728 |
| OVERGROWTH | OVERGROWTH_CRAWLERS | Monster | 139 | 14.43 | 7.32 | 0.48 | 3.70 | 6/556 |
| HIVE | BOWLBUGS_NORMAL | Monster | 195 | 9.73 | 6.95 | 0.75 | 3.64 | 0/780 |
| GLORY | OWL_MAGISTRATE_NORMAL | Monster | 78 | 8.08 | 6.03 | -1.41 | 3.59 | 0/312 |
| HIVE | CHOMPERS_NORMAL | Monster | 254 | 11.38 | 5.38 | -1.01 | 3.58 | 0/1016 |
| HIVE | HUNTER_KILLER_NORMAL | Monster | 261 | 10.88 | 6.67 | 0.46 | 3.54 | 0/1044 |
| UNDERDOCKS | SEAPUNK_NORMAL | Monster | 94 | 15.14 | 6.28 | -0.04 | 3.44 | 1/376 |
| HIVE | TUNNELER_WEAK | Monster弱 | 465 | 7.09 | 5.31 | -0.54 | 3.43 | 1/1860 |
| UNDERDOCKS | SKULKING_COLONY_ELITE | Elite | 282 | 16.95 | 5.50 | -0.14 | 3.35 | 0/1128 |
| HIVE | EXOSKELETONS_NORMAL | Monster | 177 | 5.62 | 4.39 | 0.45 | 3.20 | 0/708 |
| HIVE | LOUSE_PROGENITOR_NORMAL | Monster | 205 | 8.49 | 5.44 | -0.56 | 3.05 | 0/820 |
| HIVE | SPINY_TOAD_NORMAL | Monster | 208 | 8.35 | 4.75 | -0.49 | 3.04 | 0/832 |
| OVERGROWTH | SNAPPING_JAXFRUIT_NORMAL | Monster | 115 | 12.06 | 5.42 | 0.18 | 2.93 | 0/460 |
| OVERGROWTH | RUBY_RAIDERS_NORMAL | Monster | 140 | 11.20 | 5.58 | -0.53 | 2.84 | 0/560 |
| OVERGROWTH | NIBBITS_NORMAL | Monster | 184 | 10.73 | 5.36 | -0.34 | 2.83 | 0/736 |
| GLORY | SCROLLS_OF_BITING_WEAK | Monster弱 | 384 | 4.57 | 3.93 | 0.03 | 2.79 | 0/1536 |
| UNDERDOCKS | HAUNTED_SHIP_NORMAL | Monster | 102 | 8.09 | 4.89 | -0.59 | 2.68 | 0/408 |
| UNDERDOCKS | GREMLIN_MERC_NORMAL | Monster | 144 | 8.97 | 4.48 | -0.52 | 2.68 | 0/576 |
| OVERGROWTH | SLIMES_NORMAL | Monster | 122 | 6.97 | 4.11 | 0.07 | 2.48 | 0/488 |
| GLORY | GLOBE_HEAD_NORMAL | Monster | 155 | 5.71 | 4.13 | 0.52 | 2.47 | 0/620 |
| UNDERDOCKS | CORPSE_SLUGS_NORMAL | Monster | 94 | 7.07 | 3.81 | -0.48 | 2.42 | 0/376 |
| UNDERDOCKS | TWO_TAILED_RATS_NORMAL | Monster | 127 | 8.11 | 4.65 | -1.11 | 2.38 | 1/508 |
| OVERGROWTH | FLYCONID_NORMAL | Monster | 116 | 10.54 | 4.82 | -0.60 | 2.32 | 0/464 |
| OVERGROWTH | FOGMOG_NORMAL | Monster | 156 | 6.55 | 4.03 | -0.37 | 2.22 | 0/624 |
| OVERGROWTH | MAWLER_NORMAL | Monster | 142 | 7.32 | 4.47 | -0.50 | 2.21 | 0/568 |
| UNDERDOCKS | PUNCH_CONSTRUCT_NORMAL | Monster | 137 | 5.76 | 3.54 | -0.19 | 2.14 | 0/548 |
| GLORY | TURRET_OPERATOR_WEAK | Monster弱 | 436 | 3.69 | 3.58 | -0.03 | 2.14 | 0/1744 |
| OVERGROWTH | INKLETS_NORMAL | Monster | 123 | 5.36 | 3.31 | -0.11 | 2.01 | 0/492 |
| HIVE | THIEVING_HOPPER_WEAK | Monster弱 | 429 | 3.78 | 3.55 | -0.11 | 1.99 | 0/1715 |
| OVERGROWTH | CUBEX_CONSTRUCT_NORMAL | Monster | 162 | 5.79 | 3.69 | -1.24 | 1.98 | 0/648 |
| HIVE | BOWLBUGS_WEAK | Monster弱 | 441 | 3.65 | 3.51 | 0.07 | 1.96 | 0/1764 |
| UNDERDOCKS | FOSSIL_STALKER_NORMAL | Monster | 134 | 7.34 | 4.64 | -0.20 | 1.95 | 0/536 |
| UNDERDOCKS | LIVING_FOG_NORMAL | Monster | 97 | 5.84 | 3.40 | -0.65 | 1.85 | 0/388 |
| OVERGROWTH | VINE_SHAMBLER_NORMAL | Monster | 118 | 5.69 | 3.09 | -0.37 | 1.78 | 0/472 |
| OVERGROWTH | SLITHERING_STRANGLER_NORMAL | Monster | 100 | 4.53 | 3.92 | -0.47 | 1.72 | 0/400 |
| UNDERDOCKS | SEWER_CLAM_NORMAL | Monster | 114 | 3.68 | 3.34 | -0.29 | 1.44 | 0/456 |
| HIVE | EXOSKELETONS_WEAK | Monster弱 | 432 | 2.43 | 2.15 | -0.62 | 1.40 | 0/1728 |
| UNDERDOCKS | CORPSE_SLUGS_WEAK | Monster弱 | 393 | 3.61 | 2.40 | -0.59 | 1.39 | 0/1572 |
| UNDERDOCKS | SLUDGE_SPINNER_WEAK | Monster弱 | 349 | 2.49 | 2.59 | -0.22 | 1.11 | 0/1396 |
| UNDERDOCKS | TOADPOLES_WEAK | Monster弱 | 373 | 2.84 | 2.45 | -0.17 | 1.11 | 0/1492 |
| OVERGROWTH | SHRINKER_BEETLE_WEAK | Monster弱 | 446 | 1.74 | 2.08 | -0.09 | 1.02 | 0/1784 |
| UNDERDOCKS | SEAPUNK_WEAK | Monster弱 | 407 | 2.05 | 2.35 | -0.32 | 0.99 | 0/1628 |
| OVERGROWTH | FUZZY_WURM_CRAWLER_WEAK | Monster弱 | 466 | 1.58 | 1.79 | -0.36 | 0.97 | 0/1864 |
| OVERGROWTH | SLIMES_WEAK | Monster弱 | 432 | 1.60 | 2.01 | -0.13 | 0.94 | 0/1728 |
| OVERGROWTH | NIBBITS_WEAK | Monster弱 | 466 | 1.55 | 2.09 | -0.31 | 0.81 | 0/1864 |

## 编组内区分能力：模型是否只在预测“这个怪难不难”

基线 = 对每个编组恒定预测其**训练集**标签均值（只看怪、不看构筑）。若模型对同一编组的不同构筑预测几乎不变，其预测 std 会远小于标签 std，编组内相关系数接近 0，编组内 R² 也接近 0（R² = 1 − 模型 MSE / 基线 MSE，>0 表示比基线好）。

整体：模型 pair MAE 3.95，编组均值基线 pair MAE 7.64；基线 pair R² 0.551，模型 pair R² 0.859。编组内相关系数中位数 0.82，编组内 R² 中位数 0.66；模型在 80/80 个编组上优于基线，在 0 个编组上几乎没有区分能力（R² < 0.1）。模型预测 std / 标签 std 的中位数 0.85（接近 0 表示对该编组几乎恒定预测）。

按编组内 R² 从低到高（最像“不分青红皂白”的排在前面）：

| 幕 | 编组 | 类型 | pairs | 标签 std | 预测 std | 相关 | 编组内 R² | MAE 模型 | MAE 基线 |
|---|---|---|---|---|---|---|---|---|---|
| GLORY | THE_LOST_AND_FORGOTTEN_NORMAL | Monster | 170 | 9.42 | 7.68 | 0.49 | 0.11 | 5.65 | 6.17 |
| OVERGROWTH | NIBBITS_WEAK | Monster弱 | 466 | 1.23 | 0.69 | 0.52 | 0.20 | 0.81 | 1.01 |
| GLORY | SCROLLS_OF_BITING_NORMAL | Monster | 192 | 7.14 | 7.67 | 0.61 | 0.21 | 4.58 | 6.78 |
| HIVE | THE_OBSCURA_NORMAL | Monster | 206 | 7.01 | 7.72 | 0.66 | 0.25 | 4.57 | 6.16 |
| OVERGROWTH | SLIMES_WEAK | Monster弱 | 432 | 1.48 | 0.85 | 0.55 | 0.30 | 0.94 | 1.20 |
| GLORY | FABRICATOR_NORMAL | Monster | 150 | 7.18 | 5.69 | 0.61 | 0.31 | 4.48 | 5.46 |
| OVERGROWTH | FUZZY_WURM_CRAWLER_WEAK | Monster弱 | 466 | 1.77 | 1.11 | 0.61 | 0.33 | 0.97 | 1.37 |
| GLORY | FROG_KNIGHT_NORMAL | Monster | 143 | 8.86 | 5.31 | 0.58 | 0.33 | 4.42 | 6.16 |
| OVERGROWTH | SHRINKER_BEETLE_WEAK | Monster弱 | 446 | 1.66 | 1.14 | 0.59 | 0.34 | 1.02 | 1.35 |
| GLORY | AXEBOTS_NORMAL | Monster | 179 | 12.41 | 9.21 | 0.60 | 0.35 | 7.58 | 9.08 |
| GLORY | TURRET_OPERATOR_WEAK | Monster弱 | 436 | 3.78 | 3.53 | 0.67 | 0.39 | 2.14 | 3.08 |
| HIVE | THIEVING_HOPPER_WEAK | Monster弱 | 429 | 3.46 | 2.90 | 0.65 | 0.39 | 1.99 | 2.67 |
| HIVE | EXOSKELETONS_NORMAL | Monster | 177 | 5.92 | 6.08 | 0.71 | 0.40 | 3.20 | 4.63 |
| UNDERDOCKS | SEAPUNK_WEAK | Monster弱 | 407 | 1.81 | 1.11 | 0.66 | 0.41 | 0.99 | 1.41 |
| UNDERDOCKS | SLUDGE_SPINNER_WEAK | Monster弱 | 349 | 1.84 | 1.11 | 0.65 | 0.41 | 1.11 | 1.52 |
| HIVE | TUNNELER_WEAK | Monster弱 | 465 | 6.83 | 4.93 | 0.66 | 0.43 | 3.43 | 4.84 |
| GLORY | QUEEN_BOSS | Boss | 223 | 18.61 | 16.73 | 0.68 | 0.43 | 10.35 | 16.33 |
| GLORY | TEST_SUBJECT_BOSS | Boss | 206 | 18.90 | 15.37 | 0.69 | 0.44 | 10.68 | 15.77 |
| UNDERDOCKS | CORPSE_SLUGS_WEAK | Monster弱 | 393 | 2.54 | 1.68 | 0.71 | 0.44 | 1.39 | 2.06 |
| HIVE | EXOSKELETONS_WEAK | Monster弱 | 432 | 3.71 | 2.69 | 0.70 | 0.47 | 1.40 | 2.33 |
| GLORY | DEVOTED_SCULPTOR_WEAK | Monster弱 | 441 | 8.88 | 5.96 | 0.72 | 0.49 | 4.10 | 6.45 |
| HIVE | BOWLBUGS_WEAK | Monster弱 | 441 | 3.74 | 3.03 | 0.71 | 0.50 | 1.96 | 2.96 |
| GLORY | KNIGHTS_ELITE | Elite | 348 | 17.74 | 13.89 | 0.70 | 0.50 | 9.70 | 15.11 |
| HIVE | LOUSE_PROGENITOR_NORMAL | Monster | 205 | 5.95 | 4.14 | 0.72 | 0.51 | 3.05 | 4.69 |
| GLORY | MECHA_KNIGHT_ELITE | Elite | 275 | 14.80 | 12.64 | 0.74 | 0.53 | 7.92 | 12.17 |
| UNDERDOCKS | TOADPOLES_WEAK | Monster弱 | 373 | 2.09 | 1.47 | 0.74 | 0.54 | 1.11 | 1.63 |
| GLORY | SCROLLS_OF_BITING_WEAK | Monster弱 | 384 | 5.94 | 4.71 | 0.75 | 0.57 | 2.79 | 4.30 |
| HIVE | OVICOPTER_NORMAL | Monster | 218 | 12.65 | 8.93 | 0.76 | 0.57 | 5.29 | 9.57 |
| UNDERDOCKS | SEWER_CLAM_NORMAL | Monster | 114 | 3.09 | 3.27 | 0.81 | 0.58 | 1.44 | 2.55 |
| HIVE | THE_INSATIABLE_BOSS | Boss | 146 | 19.58 | 14.96 | 0.77 | 0.60 | 10.02 | 16.43 |
| HIVE | BOWLBUGS_NORMAL | Monster | 195 | 7.31 | 7.16 | 0.79 | 0.60 | 3.64 | 5.37 |
| GLORY | SLIMED_BERSERKER_NORMAL | Monster | 182 | 9.12 | 6.59 | 0.80 | 0.61 | 3.91 | 7.13 |
| GLORY | AEONGLASS_BOSS | Boss | 203 | 19.62 | 17.71 | 0.81 | 0.63 | 8.51 | 16.61 |
| HIVE | KNOWLEDGE_DEMON_BOSS | Boss | 131 | 20.17 | 16.74 | 0.80 | 0.63 | 8.65 | 17.61 |
| HIVE | MYTES_NORMAL | Monster | 230 | 9.69 | 7.68 | 0.82 | 0.63 | 4.05 | 7.31 |
| UNDERDOCKS | SOUL_FYSH_BOSS | Boss | 89 | 18.44 | 14.83 | 0.82 | 0.65 | 8.57 | 15.68 |
| UNDERDOCKS | PUNCH_CONSTRUCT_NORMAL | Monster | 137 | 4.66 | 3.51 | 0.81 | 0.66 | 2.14 | 3.87 |
| UNDERDOCKS | HAUNTED_SHIP_NORMAL | Monster | 102 | 5.73 | 4.63 | 0.82 | 0.66 | 2.68 | 4.72 |
| GLORY | SOUL_NEXUS_ELITE | Elite | 278 | 12.02 | 10.25 | 0.81 | 0.66 | 5.34 | 9.77 |
| HIVE | KAISER_CRAB_BOSS | Boss | 105 | 17.68 | 15.54 | 0.82 | 0.66 | 8.00 | 15.04 |
| GLORY | GLOBE_HEAD_NORMAL | Monster | 155 | 5.96 | 5.44 | 0.82 | 0.66 | 2.47 | 4.98 |
| OVERGROWTH | THE_KIN_BOSS | Boss | 125 | 18.65 | 14.47 | 0.86 | 0.68 | 7.88 | 16.50 |
| OVERGROWTH | INKLETS_NORMAL | Monster | 123 | 4.68 | 4.05 | 0.81 | 0.68 | 2.01 | 4.17 |
| GLORY | CONSTRUCT_MENAGERIE_NORMAL | Monster | 113 | 13.22 | 10.85 | 0.84 | 0.69 | 5.79 | 10.66 |
| HIVE | CHOMPERS_NORMAL | Monster | 254 | 8.93 | 7.87 | 0.84 | 0.70 | 3.58 | 6.97 |
| UNDERDOCKS | CORPSE_SLUGS_NORMAL | Monster | 94 | 6.11 | 5.29 | 0.84 | 0.71 | 2.42 | 4.78 |
| UNDERDOCKS | GREMLIN_MERC_NORMAL | Monster | 144 | 6.42 | 5.36 | 0.84 | 0.71 | 2.68 | 5.02 |
| HIVE | INFESTED_PRISMS_ELITE | Elite | 415 | 15.56 | 12.20 | 0.84 | 0.71 | 6.58 | 13.01 |
| OVERGROWTH | VANTOM_BOSS | Boss | 132 | 18.21 | 14.76 | 0.85 | 0.71 | 7.21 | 15.18 |
| GLORY | OWL_MAGISTRATE_NORMAL | Monster | 78 | 10.38 | 6.91 | 0.89 | 0.72 | 3.59 | 7.47 |
| HIVE | HUNTER_KILLER_NORMAL | Monster | 261 | 8.58 | 8.51 | 0.85 | 0.72 | 3.54 | 7.03 |
| UNDERDOCKS | LIVING_FOG_NORMAL | Monster | 97 | 4.87 | 4.08 | 0.86 | 0.73 | 1.85 | 3.74 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | Boss | 95 | 18.29 | 16.18 | 0.86 | 0.73 | 6.94 | 15.50 |
| OVERGROWTH | SLIMES_NORMAL | Monster | 122 | 6.25 | 6.04 | 0.86 | 0.73 | 2.48 | 5.42 |
| HIVE | SPINY_TOAD_NORMAL | Monster | 208 | 7.82 | 6.82 | 0.86 | 0.73 | 3.04 | 5.80 |
| OVERGROWTH | MAWLER_NORMAL | Monster | 142 | 5.70 | 5.12 | 0.87 | 0.74 | 2.21 | 4.68 |
| HIVE | SLUMBERING_BEETLE_NORMAL | Monster | 187 | 14.60 | 13.12 | 0.86 | 0.74 | 5.37 | 10.80 |
| HIVE | DECIMILLIPEDE_ELITE | Elite | 398 | 17.03 | 16.05 | 0.87 | 0.75 | 6.28 | 13.89 |
| HIVE | ENTOMANCER_ELITE | Elite | 406 | 18.00 | 15.58 | 0.87 | 0.76 | 6.42 | 14.10 |
| OVERGROWTH | CUBEX_CONSTRUCT_NORMAL | Monster | 162 | 5.80 | 4.28 | 0.92 | 0.76 | 1.98 | 4.28 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | Boss | 93 | 21.96 | 19.06 | 0.88 | 0.77 | 7.86 | 19.90 |
| OVERGROWTH | VINE_SHAMBLER_NORMAL | Monster | 118 | 5.06 | 3.78 | 0.89 | 0.77 | 1.78 | 4.10 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | Boss | 130 | 18.83 | 16.87 | 0.89 | 0.77 | 7.04 | 15.66 |
| OVERGROWTH | FOGMOG_NORMAL | Monster | 156 | 6.32 | 5.71 | 0.88 | 0.77 | 2.22 | 4.65 |
| UNDERDOCKS | SKULKING_COLONY_ELITE | Elite | 282 | 9.31 | 7.93 | 0.89 | 0.79 | 3.35 | 7.53 |
| OVERGROWTH | SLITHERING_STRANGLER_NORMAL | Monster | 100 | 5.11 | 4.35 | 0.90 | 0.80 | 1.72 | 4.02 |
| UNDERDOCKS | SEAPUNK_NORMAL | Monster | 94 | 10.05 | 9.10 | 0.89 | 0.80 | 3.44 | 7.99 |
| OVERGROWTH | BYGONE_EFFIGY_ELITE | Elite | 436 | 16.52 | 15.01 | 0.90 | 0.81 | 5.42 | 13.47 |
| UNDERDOCKS | TWO_TAILED_RATS_NORMAL | Monster | 127 | 7.76 | 6.62 | 0.91 | 0.81 | 2.38 | 6.02 |
| UNDERDOCKS | FOSSIL_STALKER_NORMAL | Monster | 134 | 6.24 | 5.45 | 0.90 | 0.82 | 1.95 | 4.89 |
| UNDERDOCKS | CULTISTS_NORMAL | Monster | 146 | 17.38 | 15.18 | 0.91 | 0.82 | 5.55 | 13.63 |
| OVERGROWTH | FLYCONID_NORMAL | Monster | 116 | 7.40 | 6.40 | 0.92 | 0.83 | 2.32 | 6.06 |
| OVERGROWTH | NIBBITS_NORMAL | Monster | 184 | 8.72 | 7.81 | 0.91 | 0.83 | 2.83 | 7.56 |
| OVERGROWTH | BYRDONIS_ELITE | Elite | 482 | 14.42 | 12.75 | 0.92 | 0.83 | 4.37 | 11.66 |
| OVERGROWTH | RUBY_RAIDERS_NORMAL | Monster | 140 | 10.15 | 8.66 | 0.93 | 0.85 | 2.84 | 8.22 |
| UNDERDOCKS | PHANTASMAL_GARDENERS_ELITE | Elite | 326 | 20.23 | 18.39 | 0.93 | 0.85 | 5.70 | 16.85 |
| OVERGROWTH | SNAPPING_JAXFRUIT_NORMAL | Monster | 115 | 9.85 | 9.37 | 0.92 | 0.85 | 2.93 | 8.52 |
| UNDERDOCKS | TERROR_EEL_ELITE | Elite | 299 | 16.25 | 14.60 | 0.93 | 0.85 | 4.74 | 12.31 |
| OVERGROWTH | PHROG_PARASITE_ELITE | Elite | 441 | 19.76 | 18.79 | 0.92 | 0.85 | 5.44 | 17.01 |
| OVERGROWTH | OVERGROWTH_CRAWLERS | Monster | 139 | 14.10 | 13.55 | 0.93 | 0.87 | 3.70 | 12.05 |

各 Boss 编组内的预测分布（分位数），对照标签均值分布：

| 幕 | Boss | pairs | 标签 10%/50%/90% | 预测 10%/50%/90% |
|---|---|---|---|---|
| GLORY | AEONGLASS_BOSS | 203 | 22 / 60 / 70 | 23 / 56 / 68 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | 130 | 14 / 37 / 68 | 16 / 35 / 62 |
| HIVE | KAISER_CRAB_BOSS | 105 | 21 / 50 / 70 | 27 / 53 / 68 |
| HIVE | KNOWLEDGE_DEMON_BOSS | 131 | 17 / 52 / 70 | 21 / 44 / 67 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | 93 | 14 / 47 / 70 | 17 / 42 / 69 |
| GLORY | QUEEN_BOSS | 223 | 19 / 52 / 70 | 25 / 51 / 68 |
| UNDERDOCKS | SOUL_FYSH_BOSS | 89 | 16 / 35 / 67 | 16 / 34 / 56 |
| GLORY | TEST_SUBJECT_BOSS | 206 | 17 / 49 / 70 | 26 / 51 / 69 |
| HIVE | THE_INSATIABLE_BOSS | 146 | 18 / 45 / 70 | 24 / 45 / 60 |
| OVERGROWTH | THE_KIN_BOSS | 125 | 18 / 40 / 70 | 27 / 48 / 66 |
| OVERGROWTH | VANTOM_BOSS | 132 | 14 / 33 / 64 | 15 / 33 / 53 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | 95 | 15 / 46 / 65 | 23 / 39 / 65 |

## 按房间类型、幕、来源类型

### 房间类型

| 房间类型 | pairs | 平均标签 | 偏差 | MAE | MAE lightgbm | MAE repo_mlp | MAE rtdl_mlp | MAE rtdl_resnet | MAE tabm | MAE ensemble |
|---|---|---|---|---|---|---|---|---|---|---|
| Boss | 1678 | 44.88 | -0.51 | 8.75 | 11.43 | 10.61 | 10.31 | 9.45 | 9.78 | 9.16 |
| Elite | 4386 | 22.96 | -0.77 | 5.92 | 7.60 | 6.76 | 7.06 | 6.33 | 6.63 | 6.00 |
| Monster | 6309 | 9.30 | -0.32 | 3.50 | 4.37 | 3.90 | 3.98 | 3.62 | 3.77 | 3.47 |
| Monster(weak) | 6360 | 3.31 | -0.33 | 1.76 | 2.12 | 1.87 | 1.90 | 1.81 | 1.90 | 1.74 |

### 幕

| 幕 | pairs | 平均标签 | 偏差 | MAE | MAE lightgbm | MAE repo_mlp | MAE rtdl_mlp | MAE rtdl_resnet | MAE tabm | MAE ensemble |
|---|---|---|---|---|---|---|---|---|---|---|
| GLORY | 4156 | 16.58 | -0.45 | 5.68 | 7.07 | 6.53 | 6.35 | 6.03 | 6.26 | 5.77 |
| HIVE | 5509 | 13.82 | -0.21 | 4.28 | 5.45 | 4.97 | 5.07 | 4.60 | 4.76 | 4.40 |
| OVERGROWTH | 5173 | 12.23 | -0.44 | 2.97 | 3.79 | 3.20 | 3.37 | 3.03 | 3.20 | 2.89 |
| UNDERDOCKS | 3895 | 12.17 | -0.78 | 2.91 | 3.74 | 3.30 | 3.52 | 3.07 | 3.23 | 2.96 |

### 来源类型

| 来源类型 | pairs | 平均标签 | 偏差 | MAE | MAE lightgbm | MAE repo_mlp | MAE rtdl_mlp | MAE rtdl_resnet | MAE tabm | MAE ensemble |
|---|---|---|---|---|---|---|---|---|---|---|
| mutation | 3834 | 14.57 | -0.53 | 5.05 | 6.23 | 5.93 | 5.80 | 5.51 | 5.64 | 5.17 |
| real | 14899 | 13.42 | -0.42 | 3.66 | 4.68 | 4.11 | 4.24 | 3.82 | 4.01 | 3.68 |

### 牌组张数

| 牌组张数 | pairs | 平均标签 | 偏差 | MAE |
|---|---|---|---|---|
| [12, 16) | 2080 | 6.35 | -0.31 | 1.60 |
| [16, 20) | 4800 | 12.26 | -0.40 | 3.00 |
| [20, 25) | 5402 | 13.74 | -0.54 | 4.15 |
| [25, 30) | 3593 | 15.43 | -0.56 | 4.86 |
| [30, 46) | 2858 | 18.90 | -0.32 | 5.70 |

### 遗物件数

| 遗物件数 | pairs | 平均标签 | 偏差 | MAE |
|---|---|---|---|---|
| [0, 3) | 4043 | 9.84 | -0.46 | 2.19 |
| [3, 5) | 3152 | 12.90 | -0.52 | 3.25 |
| [5, 8) | 4287 | 13.51 | -0.54 | 3.96 |
| [8, 12) | 3506 | 14.12 | -0.13 | 4.65 |
| [12, 40) | 3745 | 18.13 | -0.56 | 5.74 |

## 模型分歧

各模型预测极差的中位数 5.14 HP，90% 分位 15.60。分歧最大的 pair 与其真值：

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — mutation / mut-v2 / 构筑 `2db113f1c893`
- 牌组 26 张：ACCELERANT, ACCELERANT+1, ADRENALINE, APPARITION×2, ASCENDERS_BANE, ASSASSINATE+1, BUBBLE_BUBBLE, CLUMSY, DEFEND_SILENT, DEFEND_SILENT+1, ECHOING_SLASH+1, GREED, HAZE+1, MIRAGE+1×2, NEUTRALIZE, NOXIOUS_FUMES+1 [SWIFT 2], OUTBREAK+1, PIERCING_WAIL, POISONED_STAB, POUNCE+1, REFLEX+1, SNAKEBITE+1, STRIKE_SILENT+1, SURVIVOR
- 遗物 20 件：RING_OF_THE_SNAKE, NEOWS_TALISMAN, RED_MASK, FESTIVE_POPPER, BOWLER_HAT, ASTROLABE, BONE_TEA(CombatsLeft=0), BRONZE_SCALES, PENDULUM(TurnsSeen=1), BAG_OF_PREPARATION, TOUGH_BANDAGES, DISTINGUISHED_CAPE, TWISTED_FUNNEL, ETERNAL_FEATHER, CHANDELIER, LETTER_OPENER, CAPTAINS_WHEEL, LUCKY_FYSH, BREAD, CENTENNIAL_PUZZLE
- 变异：large / both，改牌 4 改遗物 4，父代 `79c82507950a`
- 标签（4 个种子净掉血）：[45, 34, 40, 18] → 均值 **34.2**，组内 std 11.7，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 57.8 (+23.6, 死亡 0.34), repo_mlp 3.1 (-31.2, 死亡 0.01), rtdl_mlp 42.6 (+8.4, 死亡 0.26), rtdl_resnet 38.8 (+4.6, 死亡 0.05), set_transformer 65.7 (+31.5, 死亡 0.73), tabm 52.6 (+18.4, 死亡 0.45), ensemble 43.5 (+9.2, 死亡 0.31)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — real / real-v4 / 构筑 `16763da4cd5e`
- 牌组 27 张：ACCELERANT, ACCELERANT+1, ADRENALINE, APPARITION×3, ASCENDERS_BANE, ASSASSINATE+1, BUBBLE_BUBBLE, CLUMSY, DEFEND_SILENT, DEFEND_SILENT+1, GREED, HAZE, MIRAGE, MIRAGE+1, NEUTRALIZE, NOXIOUS_FUMES+1 [SWIFT 2], OUTBREAK, PIERCING_WAIL, POISONED_STAB, POUNCE+1, PREDATOR+1, REFLEX+1, SNAKEBITE+1, STRIKE_SILENT+1, SURVIVOR
- 遗物 16 件：RING_OF_THE_SNAKE, NEOWS_TALISMAN, RED_MASK, FESTIVE_POPPER, BOWLER_HAT, ASTROLABE, BONE_TEA(CombatsLeft=1), BRONZE_SCALES, PENDULUM(TurnsSeen=0), BAG_OF_PREPARATION, TOUGH_BANDAGES, DISTINGUISHED_CAPE, TWISTED_FUNNEL, ETERNAL_FEATHER, CHANDELIER, LETTER_OPENER
- 标签（4 个种子净掉血）：[51, 40, 47, 70] → 均值 **52.0**，组内 std 12.8，死亡 1/4
- 预测（误差，死亡概率）：lightgbm 57.2 (+5.2, 死亡 0.54), repo_mlp 16.5 (-35.5, 死亡 0.15), rtdl_mlp 62.8 (+10.8, 死亡 0.65), rtdl_resnet 56.6 (+4.6, 死亡 0.43), set_transformer 69.6 (+17.6, 死亡 0.95), tabm 62.2 (+10.2, 死亡 0.71), ensemble 54.2 (+2.2, 死亡 0.57)

**GLORY / KNIGHTS_ELITE** (Elite; 怪物 FLAIL_KNIGHT, SPECTRAL_KNIGHT, MAGI_KNIGHT) — mutation / mut-v2 / 构筑 `2def2f028ee8`
- 牌组 28 张：ACCURACY+1, ACROBATICS, ADRENALINE, ASCENDERS_BANE, ASSASSINATE, BACKSTAB, BLADE_OF_INK+1, CALCULATED_GAMBLE+1, CLOAK_AND_DAGGER+1, DEFEND_SILENT×3, DEFEND_SILENT [SPIRAL 1], DEFEND_SILENT+1, HIDDEN_DAGGERS, LEADING_STRIKE, LEG_SWEEP+1, NEUTRALIZE+1, PIERCING_WAIL×2, PREPARED+1, REFLEX, RICOCHET, SALVO, STRIKE_SILENT×3, THE_BOMB+1
- 遗物 13 件：RING_OF_THE_SNAKE, LOST_COFFER, RAZOR_TOOTH, GIRYA(TimesLifted=2), KUSARIGAMA, YUMMY_COOKIE, FAKE_ANCHOR, BOOK_OF_FIVE_RINGS(CardsAdded=3), STONE_CALENDAR, SNECKO_SKULL, FIDDLE, RINGING_TRIANGLE, HAPPY_FLOWER(TurnsSeen=1)
- 变异：large / cards，改牌 3 改遗物 0，父代 `7c2986d9e438`
- 标签（4 个种子净掉血）：[39, 14, 53, 65] → 均值 **42.8**，组内 std 21.9，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 18.9 (-23.9, 死亡 0.01), repo_mlp 64.4 (+21.7, 死亡 0.36), rtdl_mlp 34.6 (-8.1, 死亡 0.07), rtdl_resnet 30.0 (-12.7, 死亡 0.01), set_transformer 12.5 (-30.2, 死亡 0.00), tabm 24.8 (-17.9, 死亡 0.04), ensemble 30.9 (-11.9, 死亡 0.08)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — real / real-v4 / 构筑 `79c82507950a`
- 牌组 27 张：ACCELERANT, ACCELERANT+1, ADRENALINE, APPARITION×3, ASCENDERS_BANE, ASSASSINATE+1, BUBBLE_BUBBLE, CLUMSY, DEFEND_SILENT, DEFEND_SILENT+1, GREED, HAZE, MIRAGE+1×2, NEUTRALIZE, NOXIOUS_FUMES+1 [SWIFT 2], OUTBREAK, PIERCING_WAIL, POISONED_STAB, POUNCE+1, PREDATOR+1, REFLEX+1, SNAKEBITE+1, STRIKE_SILENT+1, SURVIVOR
- 遗物 16 件：RING_OF_THE_SNAKE, NEOWS_TALISMAN, RED_MASK, FESTIVE_POPPER, BOWLER_HAT, ASTROLABE, BONE_TEA(CombatsLeft=0), BRONZE_SCALES, PENDULUM(TurnsSeen=1), BAG_OF_PREPARATION, TOUGH_BANDAGES, DISTINGUISHED_CAPE, TWISTED_FUNNEL, ETERNAL_FEATHER, CHANDELIER, LETTER_OPENER
- 标签（4 个种子净掉血）：[42, 70, 70, 70] → 均值 **63.0**，组内 std 14.0，死亡 3/4
- 预测（误差，死亡概率）：lightgbm 58.4 (-4.6, 死亡 0.54), repo_mlp 18.3 (-44.7, 死亡 0.32), rtdl_mlp 64.4 (+1.4, 死亡 0.71), rtdl_resnet 57.4 (-5.6, 死亡 0.46), set_transformer 70.0 (+7.0, 死亡 0.97), tabm 63.3 (+0.3, 死亡 0.75), ensemble 55.3 (-7.7, 死亡 0.63)

## 最严重高估（预测 ≫ 标签）

模型认为会掉很多血，实际老师打得轻松。

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — mutation / mut-v2 / 构筑 `23442a5e5261`
- 牌组 24 张：ACCURACY+1, ASCENDERS_BANE, ASSASSINATE+1, BACKFLIP+1, BLADE_DANCE, CLOAK_AND_DAGGER, DEFEND_SILENT, DEFEND_SILENT+1, DEFLECT, FOOTWORK+1, INFINITE_BLADES+1 [SWIFT 2], KNIFE_TRAP+1, LEG_SWEEP, NEUTRALIZE, PIERCING_WAIL, PRECISE_CUT+1, PREDATOR, PREPARED×2, PREPARED+1, STRIKE_SILENT+1, SURVIVOR+1, UP_MY_SLEEVE, UP_MY_SLEEVE [IMBUED 1]
- 遗物 14 件：RING_OF_THE_SNAKE, LARGE_CAPSULE, BRONZE_SCALES, JUZU_BRACELET, SWORD_OF_STONE(ElitesDefeated=1), WAR_PAINT, ELECTRIC_SHRYMP, DAUGHTER_OF_THE_WIND, MEAT_ON_THE_BONE, REGAL_PILLOW, MINIATURE_TENT, MEAT_CLEAVER, VAMBRACE, ORNAMENTAL_FAN
- 变异：small / cards，改牌 1 改遗物 0，父代 `6aeed3f902f1`
- 标签（4 个种子净掉血）：[13, 9, 0, 14] → 均值 **9.0**，组内 std 6.4，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 44.4 (+35.4, 死亡 0.14), repo_mlp 51.5 (+42.5, 死亡 0.23), rtdl_mlp 59.0 (+50.0, 死亡 0.61), rtdl_resnet 51.6 (+42.6, 死亡 0.42), set_transformer 53.1 (+44.1, 死亡 0.41), tabm 54.2 (+45.2, 死亡 0.49), ensemble 52.3 (+43.3, 死亡 0.38)

**OVERGROWTH / BYRDONIS_ELITE** (Elite; 怪物 BYRDONIS) — real / real-v3 / 构筑 `dbf10b62ab94`
- 牌组 17 张：ASCENDERS_BANE, DEFEND_SILENT×5, DODGE_AND_ROLL [NIMBLE 2], GRAND_FINALE, INJURY, NEUTRALIZE, PREPARED, STRIKE_SILENT×3, SURVIVOR, THE_HUNT, UNTOUCHABLE
- 遗物 2 件：RING_OF_THE_SNAKE, HEFTY_TABLET
- 标签（4 个种子净掉血）：[5, 23, 4, 10] → 均值 **10.5**，组内 std 8.7，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 41.9 (+31.4, 死亡 0.16), repo_mlp 49.7 (+39.2, 死亡 0.15), rtdl_mlp 52.9 (+42.4, 死亡 0.19), rtdl_resnet 56.7 (+46.2, 死亡 0.50), set_transformer 49.4 (+38.9, 死亡 0.09), tabm 57.7 (+47.2, 死亡 0.33), ensemble 51.4 (+40.9, 死亡 0.24)

**HIVE / ENTOMANCER_ELITE** (Elite; 怪物 ENTOMANCER) — real / real-v3 / 构筑 `ab3322afa2f7`
- 牌组 21 张：ASCENDERS_BANE, BLUR+1, CLOAK_AND_DAGGER+1, DEFEND_SILENT×4, DEFEND_SILENT+1, FOOTWORK+1, HIDDEN_DAGGERS, LEADING_STRIKE, NEUTRALIZE+1, PHANTOM_BLADES+1, PIERCING_WAIL, PREPARED+1, RICOCHET, STRIKE_SILENT×3, SURVIVOR, WELL_LAID_PLANS
- 遗物 8 件：RING_OF_THE_SNAKE, PERMAFROST, STONE_CALENDAR, VAJRA, PAELS_TEARS, PANTOGRAPH, REPTILE_TRINKET, WAR_PAINT
- 标签（4 个种子净掉血）：[2, 2, 15, 3] → 均值 **5.5**，组内 std 6.4，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 46.4 (+40.9, 死亡 0.14), repo_mlp 36.8 (+31.3, 死亡 0.11), rtdl_mlp 35.5 (+30.0, 死亡 0.09), rtdl_resnet 35.0 (+29.5, 死亡 0.17), set_transformer 43.3 (+37.8, 死亡 0.16), tabm 40.3 (+34.8, 死亡 0.18), ensemble 39.5 (+34.0, 死亡 0.14)

**HIVE / ENTOMANCER_ELITE** (Elite; 怪物 ENTOMANCER) — real / real-v3 / 构筑 `2992bcf2e00d`
- 牌组 21 张：ASCENDERS_BANE, BLUR, CLOAK_AND_DAGGER+1, DEFEND_SILENT×5, FOOTWORK+1, HIDDEN_DAGGERS, LEADING_STRIKE, NEUTRALIZE+1, PHANTOM_BLADES+1, PIERCING_WAIL, PREPARED+1, RICOCHET, STRIKE_SILENT×3, SURVIVOR, WELL_LAID_PLANS
- 遗物 7 件：RING_OF_THE_SNAKE, PERMAFROST, STONE_CALENDAR, VAJRA, PAELS_TEARS, PANTOGRAPH, REPTILE_TRINKET
- 标签（4 个种子净掉血）：[37, 0, 15, 11] → 均值 **15.8**，组内 std 15.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 52.3 (+36.6, 死亡 0.23), repo_mlp 39.4 (+23.6, 死亡 0.14), rtdl_mlp 36.3 (+20.5, 死亡 0.09), rtdl_resnet 43.8 (+28.0, 死亡 0.23), set_transformer 52.4 (+36.7, 死亡 0.34), tabm 45.9 (+30.2, 死亡 0.26), ensemble 45.0 (+29.3, 死亡 0.21)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — mutation / mut-v2 / 构筑 `43d2da816e8b`
- 牌组 33 张：ABRASIVE, ABRASIVE+1, ACCELERANT+1, ASCENDERS_BANE, BLUR, BUBBLE_BUBBLE+1×2, DAGGER_SPRAY+1, DEADLY_POISON+1, DEFEND_SILENT×5, DEFLECT+1, EQUILIBRIUM, ESCAPE_PLAN, FOOTWORK+1, HELLO_WORLD [SWIFT 2], LEADING_STRIKE, NOXIOUS_FUMES+1, PINPOINT, PREPARED+1×2, PROWESS+1, REFLEX, SIDESTEP, STRIKE_SILENT [SWIFT 2]×2, SUPPRESS+1, SURVIVOR [SWIFT 2], UNTOUCHABLE+1×2
- 遗物 21 件：RING_OF_THE_SNAKE, LAVA_ROCK(HasTriggered=True), FESTIVE_POPPER, STONE_CALENDAR, ETERNAL_FEATHER, JUZU_BRACELET, REGAL_PILLOW, RED_MASK, ARCHAIC_TOOTH, MEMBERSHIP_CARD, VAMBRACE, VEXING_PUZZLEBOX, GORGET, AMETHYST_AUBERGINE, BEAUTIFUL_BRACELET, AKABEKO, KUSARIGAMA, CENTENNIAL_PUZZLE, ODDLY_SMOOTH_STONE, SHURIKEN, PENDULUM(TurnsSeen=2)
- 变异：small / cards，改牌 1 改遗物 0，父代 `6b242298f0bc`
- 标签（4 个种子净掉血）：[28, 27, 2, 26] → 均值 **20.8**，组内 std 12.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 51.6 (+30.8, 死亡 0.39), repo_mlp 49.5 (+28.7, 死亡 0.42), rtdl_mlp 34.6 (+13.9, 死亡 0.16), rtdl_resnet 55.7 (+34.9, 死亡 0.57), set_transformer 57.2 (+36.4, 死亡 0.40), tabm 51.0 (+30.2, 死亡 0.40), ensemble 49.9 (+29.2, 死亡 0.39)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — mutation / mut-v2 / 构筑 `6a110fcd90d8`
- 牌组 33 张：ABRASIVE, ABRASIVE+1, ACCELERANT+1, ASCENDERS_BANE, BLUR, BUBBLE_BUBBLE+1×2, DAGGER_SPRAY+1, DEADLY_POISON+1, DEFEND_SILENT×5, DEFLECT+1, EQUILIBRIUM, ESCAPE_PLAN, FOOTWORK+1, HELLO_WORLD [SWIFT 2], LEADING_STRIKE, NOXIOUS_FUMES+1, PINPOINT, PREPARED+1×2, PROWESS+1, REFLEX, SIDESTEP, STRIKE_SILENT [SWIFT 2]×2, SUPPRESS+1, SURVIVOR [SWIFT 2], UNTOUCHABLE, UNTOUCHABLE+1
- 遗物 19 件：RING_OF_THE_SNAKE, LAVA_ROCK(HasTriggered=True), FESTIVE_POPPER, STONE_CALENDAR, ETERNAL_FEATHER, JUZU_BRACELET, RED_MASK, ARCHAIC_TOOTH, VAMBRACE, VEXING_PUZZLEBOX, GORGET, AMETHYST_AUBERGINE, BEAUTIFUL_BRACELET, KUSARIGAMA, CENTENNIAL_PUZZLE, ODDLY_SMOOTH_STONE, PENDULUM(TurnsSeen=2), MOLTEN_EGG, KUNAI
- 变异：large / relics，改牌 0 改遗物 4，父代 `6b242298f0bc`
- 标签（4 个种子净掉血）：[16, 7, 0, 34] → 均值 **14.2**，组内 std 14.7，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 51.8 (+37.6, 死亡 0.48), repo_mlp 51.1 (+36.9, 死亡 0.53), rtdl_mlp 37.8 (+23.5, 死亡 0.29), rtdl_resnet 49.3 (+35.1, 死亡 0.46), set_transformer 50.4 (+36.1, 死亡 0.22), tabm 48.3 (+34.0, 死亡 0.35), ensemble 48.1 (+33.9, 死亡 0.39)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — mutation / mut-v2 / 构筑 `c8fac89af043`
- 牌组 23 张：ACCURACY+1, ASCENDERS_BANE, ASSASSINATE+1, BACKFLIP+1, BLADE_DANCE, CLOAK_AND_DAGGER, DEFEND_SILENT, DEFEND_SILENT+1, DEFLECT, FOOTWORK+1, INFINITE_BLADES+1 [SWIFT 2], KNIFE_TRAP+1, LEG_SWEEP, MIND_BLAST, NEUTRALIZE, PIERCING_WAIL, PREPARED×2, PREPARED+1, STRIKE_SILENT+1, SURVIVOR+1, UP_MY_SLEEVE, UP_MY_SLEEVE [IMBUED 1]
- 遗物 14 件：RING_OF_THE_SNAKE, LARGE_CAPSULE, BRONZE_SCALES, JUZU_BRACELET, SWORD_OF_STONE(ElitesDefeated=1), WAR_PAINT, ELECTRIC_SHRYMP, DAUGHTER_OF_THE_WIND, MEAT_ON_THE_BONE, REGAL_PILLOW, MINIATURE_TENT, MEAT_CLEAVER, VAMBRACE, ORNAMENTAL_FAN
- 变异：small / cards，改牌 1 改遗物 0，父代 `6aeed3f902f1`
- 标签（4 个种子净掉血）：[14, 11, 22, 13] → 均值 **15.0**，组内 std 4.8，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 43.0 (+28.0, 死亡 0.12), repo_mlp 50.3 (+35.3, 死亡 0.08), rtdl_mlp 58.3 (+43.3, 死亡 0.60), rtdl_resnet 47.5 (+32.5, 死亡 0.26), set_transformer 51.0 (+36.0, 死亡 0.35), tabm 55.2 (+40.2, 死亡 0.51), ensemble 50.9 (+35.9, 死亡 0.32)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — real / real-v4 / 构筑 `93f77f84bf5b`
- 牌组 33 张：ADRENALINE+1, ASCENDERS_BANE, ASSASSINATE, BLUR, BLUR [NIMBLE 2], CALCULATED_GAMBLE×2, DEADLY_POISON×3, DEADLY_POISON+1, DEFEND_SILENT×4, DEFEND_SILENT [SPIRAL 1], ECHOING_SLASH, ESCAPE_PLAN, FASTEN+1, MAUL×6, NEUTRALIZE, NOXIOUS_FUMES, NOXIOUS_FUMES+1×2, PIERCING_WAIL+1, SIDESTEP, ULTIMATE_DEFEND, WELL_LAID_PLANS
- 遗物 17 件：RING_OF_THE_SNAKE, BOOMING_CONCH, RIPPLE_BASIN, MUMMIFIED_HAND, CENTENNIAL_PUZZLE, AKABEKO, PAELS_TEARS, TOOLBOX, GIRYA(TimesLifted=1), REGAL_PILLOW, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), CLAWS, ODDLY_SMOOTH_STONE, FRAGRANT_MUSHROOM, RED_MASK, BRONZE_SCALES, BLOOD_VIAL
- 标签（4 个种子净掉血）：[17, 8, 58, 21] → 均值 **26.0**，组内 std 22.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 59.2 (+33.2, 死亡 0.51), repo_mlp 59.1 (+33.1, 死亡 0.42), rtdl_mlp 66.2 (+40.2, 死亡 0.70), rtdl_resnet 62.7 (+36.7, 死亡 0.64), set_transformer 61.9 (+35.9, 死亡 0.56), tabm 60.7 (+34.7, 死亡 0.62), ensemble 61.6 (+35.6, 死亡 0.58)

## 最严重低估（预测 ≪ 标签）

模型认为安全，实际老师掉血多或死亡。

**GLORY / THE_LOST_AND_FORGOTTEN_NORMAL** (Monster; 怪物 THE_LOST, THE_FORGOTTEN) — real / real-v3 / 构筑 `b716d1505a8f`
- 牌组 31 张：ACROBATICS, ADRENALINE [SOULS_POWER 1], AFTERIMAGE+1, ASCENDERS_BANE, ASSASSINATE+1, CLOAK_AND_DAGGER×2, DECAY, DEFEND_SILENT×5, DODGE_AND_ROLL, EXPOSE, FAN_OF_KNIVES, FOOTWORK+1, HIDDEN_DAGGERS, INFINITE_BLADES+1, KNIFE_TRAP, LEG_SWEEP, STRIKE_SILENT×4, SUPPRESS+1, SURVIVOR, TORIC_TOUGHNESS, UNTOUCHABLE×2, UP_MY_SLEEVE
- 遗物 12 件：RING_OF_THE_SNAKE, HEFTY_TABLET, PLANISPHERE, PERMAFROST, JOSS_PAPER(CardsExhausted=2), ARCHAIC_TOOTH, GORGET, ODDLY_SMOOTH_STONE, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), BEATING_REMNANT, SNECKO_SKULL, IRON_CLUB(CardsPlayed=3)
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 13.2 (-56.8, 死亡 0.00), repo_mlp 32.3 (-37.7, 死亡 0.00), rtdl_mlp 14.4 (-55.6, 死亡 0.00), rtdl_resnet 15.5 (-54.5, 死亡 0.00), set_transformer 16.2 (-53.8, 死亡 0.01), tabm 7.8 (-62.2, 死亡 0.00), ensemble 16.6 (-53.4, 死亡 0.00)

**GLORY / QUEEN_BOSS** (Boss; 怪物 QUEEN, TORCH_HEAD_AMALGAM) — mutation / mut-v2 / 构筑 `1fe42c2fdceb`
- 牌组 35 张：ADRENALINE+1, ASCENDERS_BANE, ASSASSINATE+1, BACKFLIP, BACKSTAB+1, BOUNCING_FLASK, CORROSIVE_WAVE, DAGGER_THROW+1, DASH+1, DEFLECT, DRAMATIC_ENTRANCE+1, ESCAPE_PLAN [ADROIT 3]×2, EXPOSE+1 [GLAM 1], FINESSE [ADROIT 3], FLECHETTES+1, FOOTWORK, GRAND_FINALE+1 [CORRUPTED 1], INJURY, MAD_SCIENCE {TinkerTimeRider=4,TinkerTimeType=2}, MEMENTO_MORI+1, NEUTRALIZE, NOXIOUS_FUMES, PIERCING_WAIL+1 [GLAM 1], PREPARED, RICOCHET+1, RICOCHET+1 [GLAM 1], SERPENT_FORM, SLICE+1, SPEEDSTER [GLAM 1], STORM_OF_STEEL, SURVIVOR, TOOLS_OF_THE_TRADE, TOOLS_OF_THE_TRADE [GLAM 1], UP_MY_SLEEVE [GLAM 1]
- 遗物 23 件：RING_OF_THE_SNAKE, NEOWS_BONES, HEFTY_TABLET, LAVA_ROCK(HasTriggered=False), MAW_BANK(HasItemBeenBought=True), SHOVEL, PLANISPHERE, STRIKE_DUMMY, MOLTEN_EGG, MEAL_TICKET, PANDORAS_BOX, TOUGH_BANDAGES, VAMBRACE, BAG_OF_PREPARATION, GORGET, CLOAK_CLASP, SHURIKEN, GLITTER, WHITE_STAR, FESTIVE_POPPER, STONE_CRACKER, UNCEASING_TOP, CANDELABRA
- 变异：small / relics，改牌 0 改遗物 2，父代 `6d821a96f594`
- 标签（4 个种子净掉血）：[69, 44, 70, 61] → 均值 **61.0**，组内 std 12.0，死亡 1/4
- 预测（误差，死亡概率）：lightgbm 38.6 (-22.4, 死亡 0.11), repo_mlp 16.3 (-44.7, 死亡 0.00), rtdl_mlp 30.7 (-30.3, 死亡 0.11), rtdl_resnet 27.5 (-33.5, 死亡 0.14), set_transformer 12.2 (-48.8, 死亡 0.01), tabm 22.7 (-38.3, 死亡 0.04), ensemble 24.7 (-36.3, 死亡 0.07)

**GLORY / THE_LOST_AND_FORGOTTEN_NORMAL** (Monster; 怪物 THE_LOST, THE_FORGOTTEN) — mutation / mut-v1 / 构筑 `3087d2feb079`
- 牌组 31 张：ACROBATICS, ADRENALINE [SOULS_POWER 1], ASCENDERS_BANE, ASSASSINATE+1, CLOAK_AND_DAGGER×2, DECAY, DEFEND_SILENT×5, DODGE_AND_ROLL, EXPERTISE, EXPOSE, FAN_OF_KNIVES, FOOTWORK+1, HIDDEN_DAGGERS, INFINITE_BLADES+1, KNIFE_TRAP, LEG_SWEEP, PREP_TIME+1, STRIKE_SILENT×4, SURVIVOR, TORIC_TOUGHNESS, UNTOUCHABLE×2, UP_MY_SLEEVE
- 遗物 12 件：RING_OF_THE_SNAKE, HEFTY_TABLET, PLANISPHERE, PERMAFROST, JOSS_PAPER(CardsExhausted=2), ARCHAIC_TOOTH, GORGET, ODDLY_SMOOTH_STONE, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), BEATING_REMNANT, SNECKO_SKULL, IRON_CLUB(CardsPlayed=3)
- 变异：small / cards，改牌 2 改遗物 0，父代 `b716d1505a8f`
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 18.5 (-51.5, 死亡 0.00), repo_mlp 39.8 (-30.2, 死亡 0.01), rtdl_mlp 18.1 (-51.9, 死亡 0.00), rtdl_resnet 22.4 (-47.6, 死亡 0.00), set_transformer 22.9 (-47.1, 死亡 0.02), tabm 14.1 (-55.9, 死亡 0.00), ensemble 22.6 (-47.4, 死亡 0.01)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — mutation / mut-v2 / 构筑 `a3c7cca13f8b`
- 牌组 34 张：ABRASIVE+1, ACCELERANT+1, ACROBATICS+1, ADRENALINE+1, ASCENDERS_BANE, BACKFLIP+1×2, BACKSTAB+1, BUBBLE_BUBBLE, BULLET_TIME+1, CALCULATED_GAMBLE+1, CLOAK_AND_DAGGER, DASH, DEADLY_POISON, DEFEND_SILENT×4, DEFEND_SILENT+1, DEFLECT, DODGE_AND_ROLL+1, FOOTWORK+1×2, LEG_SWEEP+1, NEUTRALIZE, PIERCING_WAIL, PREPARED, PREPARED+1, SIDESTEP+1, SNAKEBITE+1, STRIKE_SILENT, STRIKE_SILENT+1, SURVIVOR+1, WELL_LAID_PLANS+1
- 遗物 18 件：RING_OF_THE_SNAKE, SMALL_CAPSULE, PRAYER_WHEEL, GREMLIN_HORN, HAPPY_FLOWER(TurnsSeen=0), MEAT_ON_THE_BONE, PENDULUM(TurnsSeen=0), RADIANT_PEARL, GORGET, TOXIC_EGG, PERMAFROST, THROWING_AXE, FAKE_ANCHOR, HORN_CLEAT, WAR_PAINT, WHETSTONE, PARRYING_SHIELD, LANTERN
- 变异：small / relics，改牌 0 改遗物 1，父代 `ff322c22e81f`
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 37.3 (-32.7, 死亡 0.46), repo_mlp 49.9 (-20.1, 死亡 0.52), rtdl_mlp 46.4 (-23.6, 死亡 0.49), rtdl_resnet 51.3 (-18.7, 死亡 0.60), set_transformer 23.2 (-46.8, 死亡 0.11), tabm 46.2 (-23.8, 死亡 0.43), ensemble 42.4 (-27.6, 死亡 0.43)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — real / real-v3 / 构筑 `ff322c22e81f`
- 牌组 34 张：ABRASIVE+1, ACCELERANT+1, ACROBATICS+1, ADRENALINE+1, ASCENDERS_BANE, BACKFLIP+1×2, BACKSTAB+1, BUBBLE_BUBBLE, BULLET_TIME+1, CALCULATED_GAMBLE+1, CLOAK_AND_DAGGER, DASH, DEADLY_POISON, DEFEND_SILENT×4, DEFEND_SILENT+1, DEFLECT, DODGE_AND_ROLL+1, FOOTWORK+1×2, LEG_SWEEP+1, NEUTRALIZE, PIERCING_WAIL, PREPARED, PREPARED+1, SIDESTEP+1, SNAKEBITE+1, STRIKE_SILENT, STRIKE_SILENT+1, SURVIVOR+1, WELL_LAID_PLANS+1
- 遗物 18 件：RING_OF_THE_SNAKE, SMALL_CAPSULE, PRAYER_WHEEL, GREMLIN_HORN, HAPPY_FLOWER(TurnsSeen=0), MEAT_ON_THE_BONE, PENDULUM(TurnsSeen=0), RADIANT_PEARL, GORGET, TOXIC_EGG, ODDLY_SMOOTH_STONE, PERMAFROST, THROWING_AXE, FAKE_ANCHOR, HORN_CLEAT, WAR_PAINT, WHETSTONE, PARRYING_SHIELD
- 标签（4 个种子净掉血）：[70, 70, 57, 70] → 均值 **66.8**，组内 std 6.5，死亡 3/4
- 预测（误差，死亡概率）：lightgbm 35.7 (-31.0, 死亡 0.44), repo_mlp 47.5 (-19.2, 死亡 0.49), rtdl_mlp 33.3 (-33.5, 死亡 0.32), rtdl_resnet 49.1 (-17.6, 死亡 0.56), set_transformer 20.3 (-46.4, 死亡 0.08), tabm 44.4 (-22.3, 死亡 0.39), ensemble 38.4 (-28.3, 死亡 0.38)

**GLORY / QUEEN_BOSS** (Boss; 怪物 QUEEN, TORCH_HEAD_AMALGAM) — mutation / mut-v2 / 构筑 `1326377fdfa7`
- 牌组 35 张：ADRENALINE+1, ASCENDERS_BANE, ASSASSINATE+1, BACKFLIP, BACKSTAB+1, BOUNCING_FLASK, CORROSIVE_WAVE, DAGGER_THROW+1, DASH+1, DEFLECT, DRAMATIC_ENTRANCE+1, ESCAPE_PLAN [ADROIT 3]×2, EXPOSE+1 [GLAM 1], FINESSE [ADROIT 3], FLECHETTES+1, FOOTWORK, GRAND_FINALE+1 [CORRUPTED 1], INJURY, MAD_SCIENCE {TinkerTimeRider=4,TinkerTimeType=2}, MEMENTO_MORI+1, NEUTRALIZE, NOXIOUS_FUMES, PIERCING_WAIL+1 [GLAM 1], PREPARED, RICOCHET+1, RICOCHET+1 [GLAM 1], SERPENT_FORM, SLICE+1, SPEEDSTER [GLAM 1], STORM_OF_STEEL, SURVIVOR, TOOLS_OF_THE_TRADE, TOOLS_OF_THE_TRADE [GLAM 1], UP_MY_SLEEVE [GLAM 1]
- 遗物 22 件：RING_OF_THE_SNAKE, NEOWS_BONES, HEFTY_TABLET, LAVA_ROCK(HasTriggered=False), MAW_BANK(HasItemBeenBought=True), SHOVEL, PLANISPHERE, STRIKE_DUMMY, MOLTEN_EGG, MEAL_TICKET, PANDORAS_BOX, TOUGH_BANDAGES, VAMBRACE, BAG_OF_PREPARATION, GORGET, CLOAK_CLASP, SHURIKEN, GLITTER, WHITE_STAR, FESTIVE_POPPER, STONE_CRACKER, UNCEASING_TOP
- 变异：large / relics，改牌 0 改遗物 2，父代 `6d821a96f594`
- 标签（4 个种子净掉血）：[60, 70, 63, 48] → 均值 **60.2**，组内 std 9.2，死亡 1/4
- 预测（误差，死亡概率）：lightgbm 38.2 (-22.1, 死亡 0.11), repo_mlp 23.4 (-36.8, 死亡 0.02), rtdl_mlp 32.7 (-27.5, 死亡 0.13), rtdl_resnet 29.1 (-31.2, 死亡 0.15), set_transformer 13.8 (-46.4, 死亡 0.01), tabm 24.5 (-35.7, 死亡 0.04), ensemble 27.0 (-33.3, 死亡 0.08)

**HIVE / OVICOPTER_NORMAL** (Monster; 怪物 OVICOPTER, TOUGH_EGG) — real / real-v4 / 构筑 `5a6cb0ef23c6`
- 牌组 19 张：ASCENDERS_BANE, BLADE_DANCE+1, DEADLY_POISON+1, DEFEND_SILENT×4, DEFEND_SILENT+1, ESCAPE_PLAN, HIDDEN_DAGGERS+1, LEADING_STRIKE+1 [GLAM 1], NEUTRALIZE+1, PREPARED+1, STRIKE_SILENT×4, SURVIVOR [NIMBLE 2], WELL_LAID_PLANS+1
- 遗物 5 件：RING_OF_THE_SNAKE, SILKEN_TRESS(IsUsed=True), ANCHOR, GAME_PIECE, PENDULUM(TurnsSeen=0)
- 标签（4 个种子净掉血）：[46, 70, 70, 70] → 均值 **64.0**，组内 std 12.0，死亡 3/4
- 预测（误差，死亡概率）：lightgbm 21.9 (-42.1, 死亡 0.07), repo_mlp 23.2 (-40.8, 死亡 0.14), rtdl_mlp 14.5 (-49.5, 死亡 0.01), rtdl_resnet 30.4 (-33.6, 死亡 0.09), set_transformer 17.9 (-46.1, 死亡 0.01), tabm 24.6 (-39.4, 死亡 0.07), ensemble 22.1 (-41.9, 死亡 0.07)

**OVERGROWTH / PHROG_PARASITE_ELITE** (Elite; 怪物 PHROG_PARASITE, WRIGGLER) — real / real-v4 / 构筑 `4ed286a18f9a`
- 牌组 18 张：ACCURACY+1, ASCENDERS_BANE, BACKSTAB, BLADE_DANCE×2, BLUR, CALCULATED_GAMBLE, DEFEND_SILENT×5, NEUTRALIZE+1, STRIKE_SILENT×4, SURVIVOR
- 遗物 3 件：RING_OF_THE_SNAKE, JOSS_PAPER(CardsExhausted=0), TOXIC_EGG
- 标签（4 个种子净掉血）：[70, 62, 48, 70] → 均值 **62.5**，组内 std 10.4，死亡 2/4
- 预测（误差，死亡概率）：lightgbm 29.4 (-33.1, 死亡 0.14), repo_mlp 26.1 (-36.4, 死亡 0.01), rtdl_mlp 23.6 (-38.9, 死亡 0.05), rtdl_resnet 15.6 (-46.9, 死亡 0.02), set_transformer 19.5 (-43.0, 死亡 0.01), tabm 39.3 (-23.2, 死亡 0.22), ensemble 25.6 (-36.9, 死亡 0.08)

## 高掉血但预测准确

标签均值 ≥ 25 HP 且 |误差| ≤ 2 HP 的 pair。

**OVERGROWTH / BYRDONIS_ELITE** (Elite; 怪物 BYRDONIS) — real / real-v4 / 构筑 `6bbabb74edb7`
- 牌组 18 张：AFTERIMAGE, ASCENDERS_BANE, BACKFLIP, BOUNCING_FLASK+1, DEADLY_POISON, DEFEND_SILENT×5, FLICK_FLACK, GUILTY {CombatsSeen=2}, NEUTRALIZE, STRIKE_SILENT×4, SURVIVOR
- 遗物 3 件：RING_OF_THE_SNAKE, WINGED_BOOTS(TimesUsed=0), BAG_OF_MARBLES
- 标签（4 个种子净掉血）：[41, 20, 21, 32] → 均值 **28.5**，组内 std 9.9，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 24.4 (-4.1, 死亡 0.00), repo_mlp 25.7 (-2.8, 死亡 0.00), rtdl_mlp 24.5 (-4.0, 死亡 0.00), rtdl_resnet 28.0 (-0.5, 死亡 0.00), set_transformer 30.3 (+1.8, 死亡 0.00), tabm 26.4 (-2.1, 死亡 0.00), ensemble 26.6 (-1.9, 死亡 0.00)

**GLORY / MECHA_KNIGHT_ELITE** (Elite; 怪物 MECHA_KNIGHT) — real / real-v3 / 构筑 `3d243f3df7b4`
- 牌组 32 张：ACCELERANT [GLAM 1], ACCURACY+1, ADRENALINE×2, AFTERIMAGE+1, ASCENDERS_BANE, BACKFLIP×2, BOUNCING_FLASK+1 [GLAM 1], CALCULATED_GAMBLE, CLUMSY, DAGGER_THROW, DEADLY_POISON+1, DEFEND_SILENT×4, DODGE_AND_ROLL+1, ENVENOM+1, EXPERTISE+1 [GLAM 1], FAN_OF_KNIVES, FLECHETTES+1, INFINITE_BLADES, MALAISE [IMBUED 1], MURDER, NEUTRALIZE+1, PIERCING_WAIL, PIERCING_WAIL [GLAM 1], SKEWER+1, STRIKE_SILENT, SURVIVOR, WELL_LAID_PLANS+1
- 遗物 13 件：RING_OF_THE_SNAKE, WHITE_STAR, BOWLER_HAT, PERMAFROST, KUSARIGAMA, REGAL_PILLOW, ELECTRIC_SHRYMP, GAMBLING_CHIP, PENDULUM(TurnsSeen=2), BAG_OF_PREPARATION, ICE_CREAM, GLITTER, VAJRA
- 标签（4 个种子净掉血）：[30, 13, 56, 13] → 均值 **28.0**，组内 std 20.3，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 35.8 (+7.8, 死亡 0.02), repo_mlp 34.4 (+6.4, 死亡 0.07), rtdl_mlp 22.7 (-5.3, 死亡 0.00), rtdl_resnet 25.5 (-2.5, 死亡 0.00), set_transformer 26.7 (-1.3, 死亡 0.01), tabm 15.9 (-12.1, 死亡 0.00), ensemble 26.8 (-1.2, 死亡 0.02)

**OVERGROWTH / BYRDONIS_ELITE** (Elite; 怪物 BYRDONIS) — real / real-v4 / 构筑 `bf01b4b387ef`
- 牌组 17 张：ASCENDERS_BANE, CLUMSY, DAGGER_SPRAY, DEFEND_SILENT×5, DEFLECT, LEG_SWEEP, NEUTRALIZE, STRIKE_SILENT×5, SURVIVOR
- 遗物 2 件：RING_OF_THE_SNAKE, TUNGSTEN_ROD
- 标签（4 个种子净掉血）：[62, 55, 43, 52] → 均值 **53.0**，组内 std 7.9，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 41.2 (-11.8, 死亡 0.03), repo_mlp 47.3 (-5.7, 死亡 0.02), rtdl_mlp 46.6 (-6.4, 死亡 0.01), rtdl_resnet 47.9 (-5.1, 死亡 0.02), set_transformer 54.9 (+1.9, 死亡 0.08), tabm 48.1 (-4.9, 死亡 0.05), ensemble 47.7 (-5.3, 死亡 0.04)

**OVERGROWTH / BYGONE_EFFIGY_ELITE** (Elite; 怪物 BYGONE_EFFIGY) — real / real-v4 / 构筑 `29a41765dfb1`
- 牌组 17 张：ASCENDERS_BANE, BLADE_DANCE, DEFEND_SILENT×4, DEFLECT×2, FAN_OF_KNIVES, INFINITE_BLADES, NEUTRALIZE, STRIKE_SILENT×5, SURVIVOR
- 遗物 3 件：RING_OF_THE_SNAKE, BOOMING_CONCH, LUCKY_FYSH
- 标签（4 个种子净掉血）：[28, 42, 38, 31] → 均值 **34.8**，组内 std 6.4，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 32.6 (-2.2, 死亡 0.01), repo_mlp 26.0 (-8.7, 死亡 0.00), rtdl_mlp 35.4 (+0.6, 死亡 0.00), rtdl_resnet 27.6 (-7.1, 死亡 0.00), set_transformer 32.9 (-1.8, 死亡 0.00), tabm 36.8 (+2.0, 死亡 0.01), ensemble 31.9 (-2.9, 死亡 0.00)

**OVERGROWTH / CEREMONIAL_BEAST_BOSS** (Boss; 怪物 CEREMONIAL_BEAST) — real / real-v4 / 构筑 `4e5b54d5182d`
- 牌组 20 张：ACCURACY, ASCENDERS_BANE, BLADE_DANCE, BLADE_OF_INK, DEFEND_SILENT×5, FLICK_FLACK, FOOTWORK, INFINITE_BLADES, NEUTRALIZE, PREPARED, PROWESS, STRIKE_SILENT×4, SURVIVOR
- 遗物 5 件：RING_OF_THE_SNAKE, GREMLIN_HORN, ODDLY_SMOOTH_STONE, ICE_CREAM, TOUGH_BANDAGES
- 标签（4 个种子净掉血）：[38, 60, 20, 18] → 均值 **34.0**，组内 std 19.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 56.7 (+22.7, 死亡 0.06), repo_mlp 45.4 (+11.4, 死亡 0.01), rtdl_mlp 40.8 (+6.8, 死亡 0.04), rtdl_resnet 42.6 (+8.6, 死亡 0.01), set_transformer 33.1 (-0.9, 死亡 0.00), tabm 38.9 (+4.9, 死亡 0.09), ensemble 42.9 (+8.9, 死亡 0.03)

**OVERGROWTH / PHROG_PARASITE_ELITE** (Elite; 怪物 PHROG_PARASITE, WRIGGLER) — real / real-v4 / 构筑 `cd95bebd7635`
- 牌组 16 张：ACCURACY, ASCENDERS_BANE, BYRDONIS_EGG, CLOAK_AND_DAGGER [GLAM 1], DEFEND_SILENT×5, NEUTRALIZE, STRIKE_SILENT×5, SURVIVOR
- 遗物 2 件：RING_OF_THE_SNAKE, SILKEN_TRESS(IsUsed=False)
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 63.6 (-6.4, 死亡 0.88), repo_mlp 65.5 (-4.5, 死亡 0.96), rtdl_mlp 67.3 (-2.7, 死亡 0.76), rtdl_resnet 69.7 (-0.3, 死亡 0.95), set_transformer 70.0 (+0.0, 死亡 0.99), tabm 70.0 (+0.0, 死亡 0.96), ensemble 67.7 (-2.3, 死亡 0.92)

**UNDERDOCKS / LAGAVULIN_MATRIARCH_BOSS** (Boss; 怪物 LAGAVULIN_MATRIARCH) — real / real-v4 / 构筑 `f5ee7ade9869`
- 牌组 20 张：ADRENALINE, ASCENDERS_BANE, BACKFLIP, DEFEND_SILENT×5, DEFLECT, LEADING_STRIKE, NEUTRALIZE, POISONED_STAB+1, PREPARED, STRIKE_SILENT×5, SURVIVOR, UNTOUCHABLE
- 遗物 6 件：RING_OF_THE_SNAKE, BOOMING_CONCH, THE_COURIER, HAPPY_FLOWER(TurnsSeen=1), PANTOGRAPH, CANDELABRA
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 61.5 (-8.5, 死亡 0.83), repo_mlp 48.5 (-21.5, 死亡 1.00), rtdl_mlp 70.0 (+0.0, 死亡 0.85), rtdl_resnet 70.0 (+0.0, 死亡 1.00), set_transformer 70.0 (+0.0, 死亡 0.98), tabm 69.9 (-0.1, 死亡 0.99), ensemble 65.0 (-5.0, 死亡 0.94)

**HIVE / BOWLBUGS_NORMAL** (Monster; 怪物 BOWLBUG_EGG, BOWLBUG_SILK, BOWLBUG_NECTAR, BOWLBUG_ROCK) — real / real-v3 / 构筑 `fcc1e18bff8c`
- 牌组 26 张：ABRASIVE, ACROBATICS, AFTERIMAGE, ASCENDERS_BANE, BUBBLE_BUBBLE, BUBBLE_BUBBLE+1, DEFEND_SILENT×5, EXPERTISE, FOOTWORK, NEUTRALIZE, POISONED_STAB, PREDATOR, PREPARED, REFLEX, RICOCHET, SNAKEBITE+1, STORM_OF_STEEL, STRIKE_SILENT×4, SURVIVOR
- 遗物 5 件：RING_OF_THE_SNAKE, ARCANE_SCROLL, PRAYER_WHEEL, PARRYING_SHIELD, ODDLY_SMOOTH_STONE
- 标签（4 个种子净掉血）：[39, 25, 17, 43] → 均值 **31.0**，组内 std 12.1，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 17.5 (-13.5, 死亡 0.00), repo_mlp 26.6 (-4.4, 死亡 0.00), rtdl_mlp 25.3 (-5.7, 死亡 0.00), rtdl_resnet 29.9 (-1.1, 死亡 0.00), set_transformer 31.5 (+0.5, 死亡 0.00), tabm 21.3 (-9.7, 死亡 0.00), ensemble 25.4 (-5.6, 死亡 0.00)

## 随机典型样例

无筛选随机抽取，反映一般水平。

**UNDERDOCKS / FOSSIL_STALKER_NORMAL** (Monster; 怪物 FOSSIL_STALKER) — real / real-v4 / 构筑 `02dddecc2716`
- 牌组 13 张：ASCENDERS_BANE, DEFEND_SILENT×5, FLICK_FLACK, NEUTRALIZE, SNAKEBITE, STRIKE_SILENT×3, SURVIVOR
- 遗物 2 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS
- 标签（4 个种子净掉血）：[0, 11, 25, 7] → 均值 **10.8**，组内 std 10.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 10.5 (-0.2, 死亡 0.00), repo_mlp 11.4 (+0.7, 死亡 0.00), rtdl_mlp 13.9 (+3.1, 死亡 0.00), rtdl_resnet 13.6 (+2.8, 死亡 0.00), set_transformer 14.6 (+3.9, 死亡 0.00), tabm 12.2 (+1.4, 死亡 0.00), ensemble 12.7 (+1.9, 死亡 0.00)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — real / real-v4 / 构筑 `13a57882e422`
- 牌组 33 张：ASCENDERS_BANE, BACKFLIP, BURST+1, CLOAK_AND_DAGGER, CLUMSY, DAGGER_SPRAY, DEFEND_SILENT×4, DEFEND_SILENT+1, DEFLECT×2, DODGE_AND_ROLL×2, DODGE_AND_ROLL+1, ENVENOM+1, EXPOSE [ROYALLY_APPROVED 1], FOOTWORK, FOOTWORK+1, INFINITE_BLADES+1, LEADING_STRIKE+1, NEUTRALIZE+1, OUTBREAK+1, PHANTOM_BLADES×2, PREDATOR, STRIKE_SILENT [TEZCATARAS_EMBER 1]×4, STRIKE_SILENT+1 [TEZCATARAS_EMBER 1], SURVIVOR
- 遗物 22 件：RING_OF_THE_SNAKE, WHETSTONE, STRIKE_DUMMY, MERCURY_HOURGLASS, LANTERN, PLANISPHERE, BAG_OF_MARBLES, NUTRITIOUS_SOUP, PANTOGRAPH, ANCHOR, BLOOD_VIAL, ORRERY, JUZU_BRACELET, BOOK_OF_FIVE_RINGS(CardsAdded=3), FIDDLE, ROYAL_STAMP, REGAL_PILLOW, GORGET, HAPPY_FLOWER(TurnsSeen=1), CENTENNIAL_PUZZLE, PENDULUM(TurnsSeen=0), BRONZE_SCALES
- 标签（4 个种子净掉血）：[70, 70, 70, 62] → 均值 **68.0**，组内 std 4.0，死亡 3/4
- 预测（误差，死亡概率）：lightgbm 52.6 (-15.4, 死亡 0.57), repo_mlp 57.7 (-10.3, 死亡 0.42), rtdl_mlp 52.9 (-15.1, 死亡 0.44), rtdl_resnet 61.8 (-6.2, 死亡 0.74), set_transformer 65.2 (-2.8, 死亡 0.78), tabm 64.7 (-3.3, 死亡 0.80), ensemble 59.2 (-8.8, 死亡 0.62)

**HIVE / TUNNELER_WEAK** (Monster, weak; 怪物 TUNNELER) — real / real-v4 / 构筑 `cf9ec12729a2`
- 牌组 17 张：ACCELERANT, ACROBATICS+1, ADRENALINE, ASCENDERS_BANE, BOUNCING_FLASK+1, DEFEND_SILENT×3, DEFEND_SILENT+1, ESCAPE_PLAN, HAND_TRICK, LEADING_STRIKE, NEUTRALIZE, SHADOW_STEP, SLICE, SNAKEBITE, SURVIVOR
- 遗物 8 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, WAR_PAINT, TUNING_FORK(SkillsPlayed=2), SNECKO_SKULL, ANCHOR, ODDLY_SMOOTH_STONE, BIIIG_HUG
- 标签（4 个种子净掉血）：[0, 0, 0, 0] → 均值 **0.0**，组内 std 0.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 0.5 (+0.5, 死亡 0.00), repo_mlp 1.7 (+1.7, 死亡 0.00), rtdl_mlp 2.6 (+2.6, 死亡 0.00), rtdl_resnet 2.5 (+2.5, 死亡 0.00), set_transformer 0.9 (+0.9, 死亡 0.00), tabm 3.2 (+3.2, 死亡 0.00), ensemble 1.9 (+1.9, 死亡 0.00)

**OVERGROWTH / NIBBITS_WEAK** (Monster, weak; 怪物 NIBBIT) — real / real-v4 / 构筑 `39fba56df06e`
- 牌组 14 张：ASCENDERS_BANE, DEFEND_SILENT×5, NEUTRALIZE, STRIKE_SILENT×5, SURVIVOR, THINKING_AHEAD
- 遗物 2 件：RING_OF_THE_SNAKE, LEAD_PAPERWEIGHT
- 标签（4 个种子净掉血）：[0, 0, 2, 0] → 均值 **0.5**，组内 std 1.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 2.1 (+1.6, 死亡 0.00), repo_mlp 1.4 (+0.9, 死亡 0.00), rtdl_mlp 0.8 (+0.3, 死亡 0.00), rtdl_resnet 1.1 (+0.6, 死亡 0.00), set_transformer 1.6 (+1.1, 死亡 0.00), tabm 1.0 (+0.5, 死亡 0.00), ensemble 1.3 (+0.8, 死亡 0.00)

**GLORY / TURRET_OPERATOR_WEAK** (Monster, weak; 怪物 LIVING_SHIELD, TURRET_OPERATOR) — mutation / mut-v2 / 构筑 `3c55796f048e`
- 牌组 26 张：ABRASIVE, ACROBATICS, AFTERIMAGE, ASCENDERS_BANE, BLADE_DANCE, CLOAK_AND_DAGGER, DAGGER_SPRAY, DAGGER_THROW, DEFEND_SILENT×5, FLECHETTES+1, FOOTWORK [SOWN 1], HIDDEN_DAGGERS, LEG_SWEEP, NEUTRALIZE+1, PREPARED+1, REFLEX, SERPENT_FORM+1, SIDESTEP, SNAKEBITE+1, STRANGLE, SURVIVOR, TACTICIAN
- 遗物 11 件：RING_OF_THE_SNAKE, LOST_COFFER, FESTIVE_POPPER, SNECKO_SKULL, BOWLER_HAT, BIIIG_HUG, LANTERN, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), UNSETTLING_LAMP, CENTENNIAL_PUZZLE, SAI
- 变异：small / both，改牌 2 改遗物 2，父代 `40f954d909cc`
- 标签（4 个种子净掉血）：[0, 2, 14, 4] → 均值 **5.0**，组内 std 6.2，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 3.6 (-1.4, 死亡 0.00), repo_mlp 1.2 (-3.8, 死亡 0.00), rtdl_mlp 1.2 (-3.8, 死亡 0.00), rtdl_resnet 2.0 (-3.0, 死亡 0.00), set_transformer 4.7 (-0.3, 死亡 0.00), tabm 2.2 (-2.8, 死亡 0.00), ensemble 2.5 (-2.5, 死亡 0.00)

**UNDERDOCKS / TWO_TAILED_RATS_NORMAL** (Monster; 怪物 TWO_TAILED_RAT) — real / real-v3 / 构筑 `1bc5383c3692`
- 牌组 19 张：ACCURACY+1, ASCENDERS_BANE, ASSASSINATE, CALCULATED_GAMBLE, DAGGER_SPRAY [SHARP 2], DEFEND_SILENT×5, INJURY, LEADING_STRIKE, NEUTRALIZE, STRIKE_SILENT×5, SURVIVOR
- 遗物 2 件：RING_OF_THE_SNAKE, HEFTY_TABLET
- 标签（4 个种子净掉血）：[0, 2, 0, 0] → 均值 **0.5**，组内 std 1.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 3.6 (+3.1, 死亡 0.00), repo_mlp 0.0 (-0.5, 死亡 0.00), rtdl_mlp 1.5 (+1.0, 死亡 0.00), rtdl_resnet 1.4 (+0.9, 死亡 0.00), set_transformer 1.5 (+1.0, 死亡 0.00), tabm 2.1 (+1.6, 死亡 0.00), ensemble 1.7 (+1.2, 死亡 0.00)

**HIVE / BOWLBUGS_NORMAL** (Monster; 怪物 BOWLBUG_EGG, BOWLBUG_SILK, BOWLBUG_NECTAR, BOWLBUG_ROCK) — real / real-v4 / 构筑 `fdb720286531`
- 牌组 30 张：ACCURACY, ASCENDERS_BANE, AUTOMATION, BACKFLIP, BACKSTAB, BRIGHTEST_FLAME+1 [PERFECT_FIT 1], BUBBLE_BUBBLE, CALCULATED_GAMBLE, CLOAK_AND_DAGGER, DAGGER_THROW, DEFEND_SILENT×2, DEFEND_SILENT+1, ENLIGHTENMENT, ENLIGHTENMENT+1, ENVENOM, ESCAPE_PLAN, INFINITE_BLADES, LEADING_STRIKE, LEG_SWEEP, NEUTRALIZE+1, PHANTOM_BLADES, POISONED_STAB, POUNCE, STRIKE_SILENT×2, SURVIVOR, TACTICIAN+1, UNTOUCHABLE, WELL_LAID_PLANS+1
- 遗物 8 件：RING_OF_THE_SNAKE, ORNAMENTAL_FAN, POCKETWATCH, RED_MASK, STORYBOOK, TINY_MAILBOX, LETTER_OPENER, WAR_PAINT
- 标签（4 个种子净掉血）：[7, 8, 4, 2] → 均值 **5.2**，组内 std 2.8，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 4.9 (-0.4, 死亡 0.00), repo_mlp 8.3 (+3.0, 死亡 0.00), rtdl_mlp 6.6 (+1.4, 死亡 0.00), rtdl_resnet 6.7 (+1.5, 死亡 0.00), set_transformer 4.6 (-0.6, 死亡 0.00), tabm 5.3 (+0.1, 死亡 0.00), ensemble 6.1 (+0.8, 死亡 0.00)

**HIVE / INFESTED_PRISMS_ELITE** (Elite; 怪物 INFESTED_PRISM) — real / real-v3 / 构筑 `6f1e9bfee47b`
- 牌组 29 张：ACCELERANT, ASCENDERS_BANE, BLADE_OF_INK, BUBBLE_BUBBLE, BULLET_TIME, DECAY, DEFEND_SILENT×5, DODGE_AND_ROLL, ECHOING_SLASH, EXPERTISE, FINESSE, FOOTWORK×2, LEG_SWEEP, NEUTRALIZE, NOXIOUS_FUMES, NOXIOUS_FUMES+1, PIERCING_WAIL, POUNCE, SNAKEBITE×2, STRIKE_SILENT×3, SURVIVOR
- 遗物 12 件：RING_OF_THE_SNAKE, NEW_LEAF, WHITE_BEAST_STATUE, RED_MASK, LASTING_CANDY(CombatRewardsSeen=1), PLANISPHERE, PAELS_BLOOD, TEA_OF_DISCOURTESY(CombatsLeft=0), LOST_WISP, MEMBERSHIP_CARD, POLLINOUS_CORE(TurnsSeen=2), REGAL_PILLOW
- 标签（4 个种子净掉血）：[16, 19, 6, 11] → 均值 **13.0**，组内 std 5.7，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 28.8 (+15.8, 死亡 0.00), repo_mlp 26.1 (+13.1, 死亡 0.00), rtdl_mlp 28.9 (+15.9, 死亡 0.00), rtdl_resnet 28.5 (+15.5, 死亡 0.00), set_transformer 28.6 (+15.6, 死亡 0.00), tabm 27.8 (+14.8, 死亡 0.00), ensemble 28.1 (+15.1, 死亡 0.00)

