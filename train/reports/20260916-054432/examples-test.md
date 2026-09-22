# 预测样例与误差分析

快照 `data/train-snapshots/20260916-054432`，测试集 82536 场 / 20638 对。主模型 **set_transformer**（pair MAE 4.00 HP，中位数 2.17，偏差 -0.37）。对比模型：lightgbm, repo_mlp, rtdl_mlp, rtdl_resnet, set_transformer, tabm, ensemble。误差 = 预测 − 同输入全部种子的均值，单位 HP。

## 误差分布（主模型，pair 级）

| 分位 | 25% | 50% | 75% | 90% | 95% | 99% |
|---|---|---|---|---|---|---|
| |误差| | 0.85 | 2.17 | 5.14 | 10.04 | 14.31 | 24.60 |

|误差| ≤ 2 HP 的 pair 占 47.5%，≤ 5 HP 占 74.3%，> 15 HP 占 4.5%。

注意“标签”本身是 4 个种子的均值，也带噪声：按组内 std/√n 估计，即使模型给出真实期望值，与 4 种子均值之间的 MAE 也约为 **2.41 HP**（正态近似 √(2/π)·std/√n 的平均）。因此主模型 pair MAE 4.00 中相当一部分来自标签噪声，而非模型误差。同理，“按标签均值分桶”中高标签桶的负偏差有一部分是选择效应（标签均值偶然偏高的 pair 被选进高桶），应以“按预测值分桶”判断校准。

## 校准：按预测值分桶

每桶给出 pair 数、平均预测、平均标签均值、偏差、MAE。理想情况下平均预测 ≈ 平均标签。

| 预测区间 | pairs | 平均预测 | 平均标签 | 偏差 | MAE |
|---|---|---|---|---|---|
| [0.0, 5.0) | 9111 | 2.21 | 2.56 | -0.35 | 1.59 |
| [5.0, 10.0) | 3427 | 7.25 | 8.07 | -0.82 | 3.61 |
| [10.0, 15.0) | 2118 | 12.34 | 13.13 | -0.79 | 4.84 |
| [15.0, 20.0) | 1369 | 17.32 | 18.36 | -1.04 | 5.96 |
| [20.0, 30.0) | 1664 | 24.62 | 25.75 | -1.13 | 7.24 |
| [30.0, 40.0) | 1065 | 34.63 | 34.02 | 0.61 | 9.28 |
| [40.0, 50.0) | 720 | 44.72 | 43.92 | 0.80 | 9.98 |
| [50.0, 60.0) | 506 | 54.69 | 53.36 | 1.33 | 9.71 |
| [60.0, 70.01) | 658 | 66.14 | 63.90 | 2.24 | 4.98 |

## 校准：按标签均值分桶

看模型在高掉血/死亡输入上是否系统性低估（向均值回归）。

| 标签区间 | pairs | 平均标签 | 平均预测 | 偏差 | MAE | 组内 std |
|---|---|---|---|---|---|---|
| [0.0, 5.0) | 8878 | 1.79 | 2.88 | 1.09 | 1.72 | 2.21 |
| [5.0, 10.0) | 3337 | 7.08 | 7.36 | 0.29 | 3.31 | 5.86 |
| [10.0, 15.0) | 2090 | 12.15 | 11.59 | -0.57 | 4.43 | 7.77 |
| [15.0, 20.0) | 1413 | 17.22 | 16.45 | -0.77 | 5.57 | 9.31 |
| [20.0, 30.0) | 1842 | 24.36 | 23.08 | -1.28 | 7.17 | 10.91 |
| [30.0, 40.0) | 1100 | 34.47 | 32.13 | -2.34 | 8.32 | 13.28 |
| [40.0, 50.0) | 649 | 44.78 | 40.48 | -4.30 | 8.81 | 15.51 |
| [50.0, 60.0) | 523 | 54.77 | 48.75 | -6.02 | 10.08 | 14.89 |
| [60.0, 70.01) | 806 | 66.94 | 60.62 | -6.32 | 7.16 | 4.56 |

## 死亡概率校准（row 级）

| 预测死亡概率 | rows | 平均预测 | 实际死亡率 |
|---|---|---|---|
| [0.0, 0.02) | 72012 | 0.00 | 0.00 |
| [0.02, 0.05) | 2276 | 0.03 | 0.03 |
| [0.05, 0.1) | 1627 | 0.07 | 0.09 |
| [0.1, 0.2) | 1768 | 0.15 | 0.16 |
| [0.2, 0.4) | 1612 | 0.29 | 0.32 |
| [0.4, 0.6) | 1031 | 0.49 | 0.45 |
| [0.6, 0.8) | 892 | 0.70 | 0.61 |
| [0.8, 1.01) | 1318 | 0.92 | 0.85 |

含死亡的 pair 1410 个（6.8%），其 pair MAE 8.30，偏差 -5.04；无死亡 pair MAE 3.69。全部种子死亡的 pair 333 个，平均预测 64.7 HP。

## 按怪物编组（主模型，pair 级）

按 MAE 从高到低；`弱` 为 weak 编组。

| 幕 | 编组 | 类型 | pairs | 平均标签 | 组内 std | 偏差 | MAE | 死亡场/总场 |
|---|---|---|---|---|---|---|---|---|
| GLORY | QUEEN_BOSS | Boss | 252 | 46.19 | 12.28 | 0.18 | 9.81 | 298/1005 |
| HIVE | THE_INSATIABLE_BOSS | Boss | 150 | 43.09 | 14.33 | -0.04 | 9.73 | 199/600 |
| GLORY | KNIGHTS_ELITE | Elite | 414 | 23.38 | 12.89 | -0.59 | 9.63 | 109/1656 |
| GLORY | TEST_SUBJECT_BOSS | Boss | 257 | 48.30 | 13.03 | 1.60 | 9.58 | 430/1028 |
| GLORY | AEONGLASS_BOSS | Boss | 226 | 53.57 | 11.90 | 0.08 | 9.36 | 490/904 |
| HIVE | KNOWLEDGE_DEMON_BOSS | Boss | 156 | 44.63 | 12.11 | -1.56 | 9.04 | 204/624 |
| UNDERDOCKS | SOUL_FYSH_BOSS | Boss | 103 | 37.79 | 9.72 | 0.15 | 8.75 | 60/412 |
| OVERGROWTH | THE_KIN_BOSS | Boss | 145 | 41.09 | 8.49 | 0.77 | 8.56 | 115/580 |
| GLORY | MECHA_KNIGHT_ELITE | Elite | 354 | 24.26 | 12.79 | 1.27 | 8.16 | 43/1416 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | Boss | 108 | 43.97 | 9.32 | -1.97 | 7.43 | 157/432 |
| OVERGROWTH | VANTOM_BOSS | Boss | 152 | 36.50 | 8.89 | -3.00 | 7.21 | 59/607 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | Boss | 98 | 43.39 | 8.93 | 0.24 | 6.77 | 69/392 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | Boss | 128 | 38.22 | 9.16 | -1.89 | 6.68 | 73/512 |
| HIVE | DECIMILLIPEDE_ELITE | Elite | 453 | 27.38 | 10.56 | -1.17 | 6.62 | 104/1812 |
| GLORY | THE_LOST_AND_FORGOTTEN_NORMAL | Monster | 178 | 13.62 | 8.19 | 0.57 | 6.58 | 25/711 |
| HIVE | KAISER_CRAB_BOSS | Boss | 143 | 48.73 | 9.71 | 1.46 | 6.38 | 155/572 |
| GLORY | AXEBOTS_NORMAL | Monster | 190 | 14.07 | 9.58 | -1.82 | 6.28 | 9/759 |
| UNDERDOCKS | PHANTASMAL_GARDENERS_ELITE | Elite | 347 | 26.28 | 8.34 | -1.33 | 6.17 | 111/1388 |
| HIVE | INFESTED_PRISMS_ELITE | Elite | 445 | 23.51 | 7.66 | -1.28 | 6.01 | 19/1779 |
| OVERGROWTH | PHROG_PARASITE_ELITE | Elite | 464 | 22.41 | 8.88 | 0.65 | 6.00 | 193/1856 |
| HIVE | ENTOMANCER_ELITE | Elite | 461 | 21.07 | 8.87 | -0.35 | 5.87 | 138/1844 |
| GLORY | CONSTRUCT_MENAGERIE_NORMAL | Monster | 141 | 16.50 | 8.98 | -3.29 | 5.76 | 12/564 |
| GLORY | SOUL_NEXUS_ELITE | Elite | 323 | 15.08 | 8.47 | 0.65 | 5.51 | 4/1292 |
| HIVE | THE_OBSCURA_NORMAL | Monster | 230 | 8.98 | 7.12 | 0.23 | 5.16 | 2/920 |
| UNDERDOCKS | CULTISTS_NORMAL | Monster | 146 | 16.52 | 7.96 | 0.55 | 5.13 | 22/584 |
| HIVE | OVICOPTER_NORMAL | Monster | 247 | 11.10 | 7.37 | -0.51 | 5.12 | 10/988 |
| OVERGROWTH | BYGONE_EFFIGY_ELITE | Elite | 462 | 23.46 | 7.78 | -0.10 | 5.09 | 46/1848 |
| HIVE | SLUMBERING_BEETLE_NORMAL | Monster | 205 | 14.84 | 8.84 | -1.61 | 5.06 | 18/820 |
| GLORY | OWL_MAGISTRATE_NORMAL | Monster | 126 | 9.64 | 6.56 | -0.70 | 4.66 | 0/504 |
| UNDERDOCKS | TERROR_EEL_ELITE | Elite | 328 | 23.60 | 7.25 | -1.98 | 4.64 | 29/1312 |
| GLORY | SCROLLS_OF_BITING_NORMAL | Monster | 261 | 6.61 | 6.37 | 0.67 | 4.49 | 0/1044 |
| HIVE | BOWLBUGS_NORMAL | Monster | 222 | 10.35 | 7.05 | 0.49 | 4.24 | 0/888 |
| OVERGROWTH | OVERGROWTH_CRAWLERS | Monster | 167 | 15.00 | 7.55 | -0.30 | 4.24 | 3/668 |
| HIVE | MYTES_NORMAL | Monster | 271 | 10.37 | 6.06 | -0.14 | 4.20 | 1/1084 |
| OVERGROWTH | BYRDONIS_ELITE | Elite | 521 | 21.91 | 6.48 | -0.71 | 4.15 | 24/2084 |
| GLORY | SLIMED_BERSERKER_NORMAL | Monster | 196 | 7.53 | 5.95 | -0.73 | 4.00 | 3/783 |
| GLORY | FABRICATOR_NORMAL | Monster | 188 | 7.13 | 6.68 | -0.66 | 3.76 | 0/747 |
| HIVE | TUNNELER_WEAK | Monster弱 | 508 | 7.11 | 5.20 | -0.24 | 3.74 | 1/2031 |
| HIVE | HUNTER_KILLER_NORMAL | Monster | 284 | 10.71 | 6.49 | -0.83 | 3.71 | 0/1136 |
| GLORY | DEVOTED_SCULPTOR_WEAK | Monster弱 | 483 | 5.95 | 4.96 | 0.07 | 3.71 | 4/1931 |
| GLORY | FROG_KNIGHT_NORMAL | Monster | 185 | 5.90 | 4.40 | 0.61 | 3.70 | 0/740 |
| UNDERDOCKS | SEAPUNK_NORMAL | Monster | 102 | 15.44 | 6.10 | -0.78 | 3.58 | 1/408 |
| HIVE | LOUSE_PROGENITOR_NORMAL | Monster | 227 | 8.79 | 5.49 | -1.82 | 3.55 | 1/908 |
| HIVE | CHOMPERS_NORMAL | Monster | 237 | 11.34 | 5.33 | -0.96 | 3.40 | 0/948 |
| UNDERDOCKS | SKULKING_COLONY_ELITE | Elite | 309 | 16.88 | 5.48 | -0.47 | 3.26 | 0/1236 |
| HIVE | SPINY_TOAD_NORMAL | Monster | 260 | 8.50 | 5.01 | -1.23 | 3.24 | 0/1040 |
| OVERGROWTH | RUBY_RAIDERS_NORMAL | Monster | 130 | 11.73 | 5.52 | -0.22 | 3.08 | 0/520 |
| OVERGROWTH | SNAPPING_JAXFRUIT_NORMAL | Monster | 116 | 11.88 | 5.17 | -0.30 | 3.08 | 0/464 |
| HIVE | EXOSKELETONS_NORMAL | Monster | 234 | 5.90 | 4.42 | 0.54 | 2.96 | 0/936 |
| OVERGROWTH | FLYCONID_NORMAL | Monster | 105 | 10.18 | 4.58 | -1.46 | 2.90 | 0/420 |
| OVERGROWTH | NIBBITS_NORMAL | Monster | 155 | 10.21 | 5.41 | -0.84 | 2.89 | 0/620 |
| GLORY | SCROLLS_OF_BITING_WEAK | Monster弱 | 446 | 4.72 | 4.08 | -0.96 | 2.73 | 0/1784 |
| GLORY | GLOBE_HEAD_NORMAL | Monster | 181 | 6.37 | 4.36 | 0.01 | 2.63 | 0/724 |
| UNDERDOCKS | GREMLIN_MERC_NORMAL | Monster | 151 | 8.56 | 4.35 | -0.72 | 2.61 | 0/604 |
| UNDERDOCKS | TWO_TAILED_RATS_NORMAL | Monster | 133 | 8.51 | 4.77 | -0.21 | 2.55 | 1/532 |
| UNDERDOCKS | HAUNTED_SHIP_NORMAL | Monster | 120 | 8.19 | 4.95 | -1.48 | 2.54 | 0/480 |
| OVERGROWTH | FOGMOG_NORMAL | Monster | 127 | 6.55 | 4.24 | -0.19 | 2.43 | 0/508 |
| UNDERDOCKS | CORPSE_SLUGS_NORMAL | Monster | 95 | 6.45 | 3.86 | -0.64 | 2.43 | 0/380 |
| GLORY | TURRET_OPERATOR_WEAK | Monster弱 | 526 | 4.41 | 3.91 | -0.61 | 2.33 | 0/2104 |
| OVERGROWTH | MAWLER_NORMAL | Monster | 144 | 7.07 | 4.57 | -0.13 | 2.21 | 0/576 |
| OVERGROWTH | SLIMES_NORMAL | Monster | 123 | 6.01 | 3.93 | -0.36 | 2.20 | 0/492 |
| UNDERDOCKS | FOSSIL_STALKER_NORMAL | Monster | 153 | 7.64 | 4.42 | -0.33 | 2.14 | 0/612 |
| OVERGROWTH | VINE_SHAMBLER_NORMAL | Monster | 111 | 5.77 | 3.00 | -0.63 | 2.09 | 0/444 |
| UNDERDOCKS | PUNCH_CONSTRUCT_NORMAL | Monster | 140 | 5.81 | 3.56 | -0.39 | 2.08 | 0/560 |
| OVERGROWTH | INKLETS_NORMAL | Monster | 125 | 6.35 | 3.40 | -0.46 | 2.06 | 0/500 |
| HIVE | THIEVING_HOPPER_WEAK | Monster弱 | 492 | 4.00 | 3.67 | -0.52 | 2.05 | 0/1967 |
| HIVE | BOWLBUGS_WEAK | Monster弱 | 471 | 3.66 | 3.53 | 0.01 | 2.02 | 0/1884 |
| OVERGROWTH | SLITHERING_STRANGLER_NORMAL | Monster | 92 | 5.28 | 4.58 | -0.10 | 1.76 | 0/368 |
| UNDERDOCKS | LIVING_FOG_NORMAL | Monster | 98 | 5.87 | 3.44 | 0.19 | 1.74 | 0/392 |
| OVERGROWTH | CUBEX_CONSTRUCT_NORMAL | Monster | 157 | 5.18 | 3.42 | -0.51 | 1.71 | 0/628 |
| UNDERDOCKS | SEWER_CLAM_NORMAL | Monster | 133 | 3.69 | 3.42 | -0.45 | 1.50 | 0/532 |
| UNDERDOCKS | CORPSE_SLUGS_WEAK | Monster弱 | 409 | 3.63 | 2.38 | -0.30 | 1.39 | 0/1636 |
| HIVE | EXOSKELETONS_WEAK | Monster弱 | 489 | 2.21 | 2.07 | -0.52 | 1.31 | 0/1956 |
| UNDERDOCKS | TOADPOLES_WEAK | Monster弱 | 382 | 2.90 | 2.47 | 0.10 | 1.12 | 0/1528 |
| UNDERDOCKS | SLUDGE_SPINNER_WEAK | Monster弱 | 386 | 2.50 | 2.56 | -0.05 | 1.09 | 0/1544 |
| OVERGROWTH | SHRINKER_BEETLE_WEAK | Monster弱 | 473 | 1.74 | 2.06 | -0.06 | 1.05 | 0/1892 |
| UNDERDOCKS | SEAPUNK_WEAK | Monster弱 | 425 | 2.07 | 2.38 | -0.07 | 1.05 | 0/1700 |
| OVERGROWTH | FUZZY_WURM_CRAWLER_WEAK | Monster弱 | 488 | 1.51 | 1.69 | -0.11 | 1.01 | 0/1952 |
| OVERGROWTH | SLIMES_WEAK | Monster弱 | 481 | 1.62 | 2.00 | -0.02 | 0.91 | 0/1924 |
| OVERGROWTH | NIBBITS_WEAK | Monster弱 | 494 | 1.59 | 2.13 | -0.22 | 0.84 | 0/1976 |

## 编组内区分能力：模型是否只在预测“这个怪难不难”

基线 = 对每个编组恒定预测其**训练集**标签均值（只看怪、不看构筑）。若模型对同一编组的不同构筑预测几乎不变，其预测 std 会远小于标签 std，编组内相关系数接近 0，编组内 R² 也接近 0（R² = 1 − 模型 MSE / 基线 MSE，>0 表示比基线好）。

整体：模型 pair MAE 4.00，编组均值基线 pair MAE 7.75；基线 pair R² 0.547，模型 pair R² 0.856。编组内相关系数中位数 0.82，编组内 R² 中位数 0.67；模型在 80/80 个编组上优于基线，在 0 个编组上几乎没有区分能力（R² < 0.1）。模型预测 std / 标签 std 的中位数 0.88（接近 0 表示对该编组几乎恒定预测）。

按编组内 R² 从低到高（最像“不分青红皂白”的排在前面）：

| 幕 | 编组 | 类型 | pairs | 标签 std | 预测 std | 相关 | 编组内 R² | MAE 模型 | MAE 基线 |
|---|---|---|---|---|---|---|---|---|---|
| HIVE | THE_OBSCURA_NORMAL | Monster | 230 | 8.79 | 8.13 | 0.57 | 0.21 | 5.16 | 6.71 |
| OVERGROWTH | NIBBITS_WEAK | Monster弱 | 494 | 1.25 | 0.59 | 0.52 | 0.24 | 0.84 | 1.02 |
| GLORY | SCROLLS_OF_BITING_NORMAL | Monster | 261 | 7.23 | 6.76 | 0.59 | 0.32 | 4.49 | 6.81 |
| GLORY | FROG_KNIGHT_NORMAL | Monster | 185 | 6.32 | 5.97 | 0.64 | 0.32 | 3.70 | 5.06 |
| OVERGROWTH | SHRINKER_BEETLE_WEAK | Monster弱 | 473 | 1.65 | 0.93 | 0.58 | 0.33 | 1.05 | 1.35 |
| HIVE | TUNNELER_WEAK | Monster弱 | 508 | 6.98 | 5.59 | 0.62 | 0.35 | 3.74 | 5.11 |
| OVERGROWTH | SLIMES_WEAK | Monster弱 | 481 | 1.49 | 0.79 | 0.60 | 0.35 | 0.91 | 1.19 |
| OVERGROWTH | FUZZY_WURM_CRAWLER_WEAK | Monster弱 | 488 | 1.76 | 1.06 | 0.61 | 0.37 | 1.01 | 1.38 |
| HIVE | THIEVING_HOPPER_WEAK | Monster弱 | 492 | 3.51 | 2.50 | 0.63 | 0.38 | 2.05 | 2.74 |
| UNDERDOCKS | SEAPUNK_WEAK | Monster弱 | 425 | 1.82 | 1.07 | 0.63 | 0.40 | 1.05 | 1.41 |
| GLORY | QUEEN_BOSS | Boss | 252 | 18.29 | 16.38 | 0.69 | 0.44 | 9.81 | 15.68 |
| HIVE | BOWLBUGS_WEAK | Monster弱 | 471 | 3.62 | 3.07 | 0.68 | 0.45 | 2.02 | 2.85 |
| HIVE | EXOSKELETONS_WEAK | Monster弱 | 489 | 3.46 | 2.31 | 0.70 | 0.46 | 1.31 | 2.23 |
| GLORY | FABRICATOR_NORMAL | Monster | 188 | 7.18 | 6.04 | 0.69 | 0.47 | 3.76 | 5.68 |
| GLORY | AEONGLASS_BOSS | Boss | 226 | 18.53 | 15.84 | 0.71 | 0.49 | 9.36 | 15.71 |
| UNDERDOCKS | SLUDGE_SPINNER_WEAK | Monster弱 | 386 | 1.91 | 1.12 | 0.71 | 0.49 | 1.09 | 1.56 |
| UNDERDOCKS | CORPSE_SLUGS_WEAK | Monster弱 | 409 | 2.56 | 1.82 | 0.71 | 0.49 | 1.39 | 2.09 |
| GLORY | KNIGHTS_ELITE | Elite | 414 | 17.96 | 14.55 | 0.71 | 0.50 | 9.63 | 15.35 |
| GLORY | MECHA_KNIGHT_ELITE | Elite | 354 | 14.98 | 13.19 | 0.73 | 0.50 | 8.16 | 12.24 |
| GLORY | SCROLLS_OF_BITING_WEAK | Monster弱 | 446 | 5.90 | 4.09 | 0.73 | 0.50 | 2.73 | 4.33 |
| GLORY | THE_LOST_AND_FORGOTTEN_NORMAL | Monster | 178 | 13.50 | 10.59 | 0.71 | 0.52 | 6.58 | 8.32 |
| GLORY | TEST_SUBJECT_BOSS | Boss | 257 | 19.41 | 17.38 | 0.74 | 0.52 | 9.58 | 16.51 |
| UNDERDOCKS | SEWER_CLAM_NORMAL | Monster | 133 | 3.12 | 2.90 | 0.76 | 0.53 | 1.50 | 2.51 |
| GLORY | TURRET_OPERATOR_WEAK | Monster弱 | 526 | 4.87 | 3.57 | 0.74 | 0.54 | 2.33 | 3.53 |
| GLORY | DEVOTED_SCULPTOR_WEAK | Monster弱 | 483 | 8.47 | 6.50 | 0.73 | 0.54 | 3.71 | 6.38 |
| UNDERDOCKS | SOUL_FYSH_BOSS | Boss | 103 | 17.63 | 15.82 | 0.76 | 0.55 | 8.75 | 14.64 |
| HIVE | OVICOPTER_NORMAL | Monster | 247 | 12.40 | 10.12 | 0.75 | 0.56 | 5.12 | 9.42 |
| GLORY | AXEBOTS_NORMAL | Monster | 190 | 12.42 | 7.40 | 0.78 | 0.56 | 6.28 | 9.15 |
| UNDERDOCKS | TOADPOLES_WEAK | Monster弱 | 382 | 2.15 | 1.62 | 0.75 | 0.56 | 1.12 | 1.67 |
| HIVE | THE_INSATIABLE_BOSS | Boss | 150 | 19.58 | 17.90 | 0.76 | 0.57 | 9.73 | 16.37 |
| HIVE | EXOSKELETONS_NORMAL | Monster | 234 | 6.24 | 5.91 | 0.78 | 0.58 | 2.96 | 4.87 |
| HIVE | LOUSE_PROGENITOR_NORMAL | Monster | 227 | 7.56 | 5.28 | 0.80 | 0.58 | 3.55 | 5.37 |
| UNDERDOCKS | CORPSE_SLUGS_NORMAL | Monster | 95 | 5.06 | 4.69 | 0.78 | 0.58 | 2.43 | 4.30 |
| GLORY | SLIMED_BERSERKER_NORMAL | Monster | 196 | 8.93 | 5.88 | 0.78 | 0.59 | 4.00 | 7.28 |
| OVERGROWTH | THE_KIN_BOSS | Boss | 145 | 18.29 | 16.07 | 0.77 | 0.60 | 8.56 | 16.48 |
| HIVE | BOWLBUGS_NORMAL | Monster | 222 | 8.68 | 8.65 | 0.79 | 0.60 | 4.24 | 6.44 |
| HIVE | SPINY_TOAD_NORMAL | Monster | 260 | 7.52 | 6.46 | 0.82 | 0.65 | 3.24 | 5.64 |
| HIVE | MYTES_NORMAL | Monster | 271 | 9.52 | 8.66 | 0.81 | 0.66 | 4.20 | 7.37 |
| GLORY | SOUL_NEXUS_ELITE | Elite | 323 | 12.56 | 11.66 | 0.82 | 0.66 | 5.51 | 10.08 |
| UNDERDOCKS | HAUNTED_SHIP_NORMAL | Monster | 120 | 5.73 | 4.43 | 0.86 | 0.67 | 2.54 | 4.76 |
| GLORY | OWL_MAGISTRATE_NORMAL | Monster | 126 | 11.28 | 8.92 | 0.82 | 0.67 | 4.66 | 8.21 |
| HIVE | KNOWLEDGE_DEMON_BOSS | Boss | 156 | 20.96 | 17.80 | 0.83 | 0.68 | 9.04 | 18.08 |
| OVERGROWTH | INKLETS_NORMAL | Monster | 125 | 4.87 | 4.46 | 0.83 | 0.68 | 2.06 | 4.21 |
| UNDERDOCKS | PUNCH_CONSTRUCT_NORMAL | Monster | 140 | 4.63 | 3.27 | 0.84 | 0.68 | 2.08 | 3.84 |
| OVERGROWTH | FOGMOG_NORMAL | Monster | 127 | 5.91 | 5.41 | 0.83 | 0.69 | 2.43 | 4.39 |
| GLORY | GLOBE_HEAD_NORMAL | Monster | 181 | 6.35 | 5.41 | 0.83 | 0.69 | 2.63 | 5.34 |
| HIVE | CHOMPERS_NORMAL | Monster | 237 | 8.71 | 8.28 | 0.84 | 0.69 | 3.40 | 6.89 |
| OVERGROWTH | VINE_SHAMBLER_NORMAL | Monster | 111 | 5.13 | 3.31 | 0.88 | 0.70 | 2.09 | 4.19 |
| UNDERDOCKS | GREMLIN_MERC_NORMAL | Monster | 151 | 6.53 | 5.36 | 0.84 | 0.70 | 2.61 | 5.20 |
| HIVE | HUNTER_KILLER_NORMAL | Monster | 284 | 8.72 | 7.90 | 0.84 | 0.72 | 3.71 | 7.28 |
| HIVE | INFESTED_PRISMS_ELITE | Elite | 445 | 15.03 | 12.31 | 0.85 | 0.72 | 6.01 | 12.52 |
| OVERGROWTH | FLYCONID_NORMAL | Monster | 105 | 7.44 | 6.07 | 0.88 | 0.74 | 2.90 | 6.02 |
| OVERGROWTH | VANTOM_BOSS | Boss | 152 | 18.08 | 15.38 | 0.88 | 0.74 | 7.21 | 15.28 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | Boss | 128 | 18.31 | 17.97 | 0.88 | 0.75 | 6.68 | 15.38 |
| UNDERDOCKS | LIVING_FOG_NORMAL | Monster | 98 | 4.83 | 5.04 | 0.88 | 0.75 | 1.74 | 3.67 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | Boss | 108 | 21.85 | 20.07 | 0.87 | 0.75 | 7.43 | 19.40 |
| HIVE | SLUMBERING_BEETLE_NORMAL | Monster | 205 | 13.99 | 11.87 | 0.88 | 0.76 | 5.06 | 10.29 |
| HIVE | DECIMILLIPEDE_ELITE | Elite | 453 | 16.96 | 15.75 | 0.88 | 0.76 | 6.62 | 13.61 |
| HIVE | KAISER_CRAB_BOSS | Boss | 143 | 18.08 | 16.71 | 0.87 | 0.76 | 6.38 | 15.98 |
| GLORY | CONSTRUCT_MENAGERIE_NORMAL | Monster | 141 | 15.56 | 12.86 | 0.90 | 0.76 | 5.76 | 11.86 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | Boss | 98 | 18.75 | 16.99 | 0.88 | 0.77 | 6.77 | 16.13 |
| OVERGROWTH | MAWLER_NORMAL | Monster | 144 | 6.00 | 5.46 | 0.88 | 0.77 | 2.21 | 4.72 |
| OVERGROWTH | SLIMES_NORMAL | Monster | 123 | 5.96 | 5.15 | 0.87 | 0.77 | 2.20 | 5.47 |
| OVERGROWTH | NIBBITS_NORMAL | Monster | 155 | 8.12 | 7.20 | 0.89 | 0.80 | 2.89 | 7.30 |
| UNDERDOCKS | SKULKING_COLONY_ELITE | Elite | 309 | 9.26 | 8.15 | 0.90 | 0.80 | 3.26 | 7.43 |
| OVERGROWTH | RUBY_RAIDERS_NORMAL | Monster | 130 | 9.87 | 9.09 | 0.90 | 0.81 | 3.08 | 7.89 |
| UNDERDOCKS | TWO_TAILED_RATS_NORMAL | Monster | 133 | 7.92 | 7.78 | 0.90 | 0.81 | 2.55 | 6.05 |
| HIVE | ENTOMANCER_ELITE | Elite | 461 | 18.52 | 16.28 | 0.90 | 0.81 | 5.87 | 14.22 |
| OVERGROWTH | PHROG_PARASITE_ELITE | Elite | 464 | 20.10 | 20.48 | 0.91 | 0.82 | 6.00 | 17.05 |
| OVERGROWTH | CUBEX_CONSTRUCT_NORMAL | Monster | 157 | 5.37 | 4.73 | 0.91 | 0.82 | 1.71 | 4.19 |
| OVERGROWTH | SNAPPING_JAXFRUIT_NORMAL | Monster | 116 | 9.76 | 9.27 | 0.90 | 0.82 | 3.08 | 8.48 |
| OVERGROWTH | BYGONE_EFFIGY_ELITE | Elite | 462 | 16.60 | 15.66 | 0.91 | 0.82 | 5.09 | 13.55 |
| OVERGROWTH | SLITHERING_STRANGLER_NORMAL | Monster | 92 | 5.66 | 5.24 | 0.91 | 0.82 | 1.76 | 4.29 |
| UNDERDOCKS | PHANTASMAL_GARDENERS_ELITE | Elite | 347 | 19.75 | 18.67 | 0.91 | 0.82 | 6.17 | 16.41 |
| UNDERDOCKS | CULTISTS_NORMAL | Monster | 146 | 17.05 | 15.44 | 0.91 | 0.83 | 5.13 | 13.12 |
| OVERGROWTH | BYRDONIS_ELITE | Elite | 521 | 13.95 | 13.39 | 0.91 | 0.83 | 4.15 | 11.06 |
| OVERGROWTH | OVERGROWTH_CRAWLERS | Monster | 167 | 14.04 | 13.91 | 0.91 | 0.83 | 4.24 | 11.83 |
| UNDERDOCKS | FOSSIL_STALKER_NORMAL | Monster | 153 | 7.09 | 5.87 | 0.91 | 0.83 | 2.14 | 5.54 |
| UNDERDOCKS | SEAPUNK_NORMAL | Monster | 102 | 11.46 | 9.49 | 0.92 | 0.83 | 3.58 | 9.00 |
| UNDERDOCKS | TERROR_EEL_ELITE | Elite | 328 | 15.89 | 14.64 | 0.93 | 0.85 | 4.64 | 12.13 |

各 Boss 编组内的预测分布（分位数），对照标签均值分布：

| 幕 | Boss | pairs | 标签 10%/50%/90% | 预测 10%/50%/90% |
|---|---|---|---|---|
| GLORY | AEONGLASS_BOSS | 226 | 23 / 60 / 70 | 33 / 59 / 68 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | 128 | 16 / 36 / 65 | 15 / 34 / 63 |
| HIVE | KAISER_CRAB_BOSS | 143 | 19 / 54 / 70 | 25 / 55 / 69 |
| HIVE | KNOWLEDGE_DEMON_BOSS | 156 | 13 / 49 / 70 | 15 / 44 / 67 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | 108 | 14 / 44 / 70 | 16 / 42 / 69 |
| GLORY | QUEEN_BOSS | 252 | 20 / 48 / 70 | 23 / 49 / 68 |
| UNDERDOCKS | SOUL_FYSH_BOSS | 103 | 17 / 34 / 66 | 18 / 36 / 62 |
| GLORY | TEST_SUBJECT_BOSS | 257 | 17 / 51 / 70 | 25 / 53 / 70 |
| HIVE | THE_INSATIABLE_BOSS | 150 | 14 / 45 / 70 | 17 / 46 / 67 |
| OVERGROWTH | THE_KIN_BOSS | 145 | 19 / 37 / 69 | 23 / 40 / 66 |
| OVERGROWTH | VANTOM_BOSS | 152 | 15 / 33 / 64 | 14 / 33 / 57 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | 98 | 16 / 46 / 68 | 23 / 43 / 69 |

## 按房间类型、幕、来源类型

### 房间类型

| 房间类型 | pairs | 平均标签 | 偏差 | MAE | MAE lightgbm | MAE repo_mlp | MAE rtdl_mlp | MAE rtdl_resnet | MAE tabm | MAE ensemble |
|---|---|---|---|---|---|---|---|---|---|---|
| Boss | 1918 | 44.76 | -0.17 | 8.55 | 11.40 | 9.98 | 10.76 | 9.62 | 9.96 | 9.10 |
| Elite | 4881 | 22.63 | -0.45 | 5.94 | 7.62 | 6.70 | 7.04 | 6.31 | 6.61 | 6.03 |
| Monster | 6886 | 9.31 | -0.49 | 3.60 | 4.57 | 3.91 | 4.02 | 3.72 | 3.95 | 3.59 |
| Monster(weak) | 6953 | 3.34 | -0.24 | 1.79 | 2.15 | 1.89 | 1.84 | 1.79 | 1.95 | 1.74 |

### 幕

| 幕 | pairs | 平均标签 | 偏差 | MAE | MAE lightgbm | MAE repo_mlp | MAE rtdl_mlp | MAE rtdl_resnet | MAE tabm | MAE ensemble |
|---|---|---|---|---|---|---|---|---|---|---|
| GLORY | 4927 | 16.65 | -0.12 | 5.59 | 7.18 | 6.21 | 6.59 | 5.99 | 6.48 | 5.80 |
| HIVE | 6185 | 13.84 | -0.54 | 4.27 | 5.53 | 4.88 | 5.00 | 4.56 | 4.72 | 4.36 |
| OVERGROWTH | 5360 | 12.23 | -0.30 | 3.05 | 3.83 | 3.24 | 3.36 | 3.12 | 3.25 | 2.95 |
| UNDERDOCKS | 4166 | 12.11 | -0.50 | 2.95 | 3.68 | 3.30 | 3.37 | 3.08 | 3.25 | 2.96 |

### 来源类型

| 来源类型 | pairs | 平均标签 | 偏差 | MAE | MAE lightgbm | MAE repo_mlp | MAE rtdl_mlp | MAE rtdl_resnet | MAE tabm | MAE ensemble |
|---|---|---|---|---|---|---|---|---|---|---|
| mutation | 4999 | 15.06 | -0.28 | 5.04 | 6.41 | 5.63 | 5.89 | 5.41 | 5.76 | 5.18 |
| real | 15639 | 13.33 | -0.40 | 3.67 | 4.69 | 4.08 | 4.22 | 3.85 | 4.05 | 3.70 |

### 牌组张数

| 牌组张数 | pairs | 平均标签 | 偏差 | MAE |
|---|---|---|---|---|
| [12, 16) | 2247 | 6.50 | -0.13 | 1.61 |
| [16, 20) | 5062 | 12.24 | -0.33 | 3.10 |
| [20, 25) | 5778 | 13.34 | -0.59 | 4.01 |
| [25, 30) | 4138 | 15.66 | -0.65 | 4.70 |
| [30, 46) | 3413 | 19.10 | 0.12 | 6.07 |

### 遗物件数

| 遗物件数 | pairs | 平均标签 | 偏差 | MAE |
|---|---|---|---|---|
| [0, 3) | 4004 | 9.37 | -0.20 | 2.14 |
| [3, 5) | 3296 | 13.12 | -0.47 | 3.33 |
| [5, 8) | 4916 | 13.84 | -0.80 | 4.08 |
| [8, 12) | 3850 | 14.03 | -0.29 | 4.42 |
| [12, 40) | 4572 | 17.68 | -0.06 | 5.68 |

## 模型分歧

各模型预测极差的中位数 5.11 HP，90% 分位 15.69。分歧最大的 pair 与其真值：

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — mutation / mut-v2 / 构筑 `f1c1233462ed`
- 牌组 27 张：ACCELERANT+1, ACROBATICS, ADRENALINE+1, ASCENDERS_BANE, BULLET_TIME+1, BURST, CALCULATED_GAMBLE, DEADLY_POISON+1, DEFEND_SILENT×5, DRAMATIC_ENTRANCE+1, ESCAPE_PLAN+1, HAZE+1, MASTER_PLANNER+1, NEUTRALIZE, NORMALITY, OUTBREAK+1, PIERCING_WAIL, POUNCE+1, REFLEX+1, STRIKE_SILENT×3, SURVIVOR
- 遗物 16 件：RING_OF_THE_SNAKE, HEFTY_TABLET, BOOK_OF_FIVE_RINGS(CardsAdded=1), HAPPY_FLOWER(TurnsSeen=0), STONE_CRACKER, AKABEKO, MOLTEN_EGG, RED_MASK, SPIKED_GAUNTLETS, FAKE_ANCHOR, FAKE_VENERABLE_TEA_SET(GainEnergyInNextCombat=False), FAKE_HAPPY_FLOWER(TurnsSeen=3), ROYAL_POISON, FESTIVE_POPPER, ANCHOR, TWISTED_FUNNEL
- 变异：large / cards，改牌 4 改遗物 0，父代 `3dc187746e62`
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 70.0 (+0.0, 死亡 0.93), repo_mlp 17.8 (-52.2, 死亡 0.95), rtdl_mlp 70.0 (+0.0, 死亡 1.00), rtdl_resnet 67.8 (-2.2, 死亡 1.00), set_transformer 69.7 (-0.3, 死亡 0.99), tabm 70.0 (+0.0, 死亡 0.96), ensemble 60.9 (-9.1, 死亡 0.97)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — mutation / mut-v1 / 构筑 `f7f2dfae3846`
- 牌组 21 张：ACROBATICS+1, ASCENDERS_BANE, CALCULATED_GAMBLE+1, DEFEND_SILENT×5, FLICK_FLACK, NOXIOUS_FUMES, PIERCING_WAIL, PREPARED, PREPARED [ADROIT 3], RICOCHET+1 [MOMENTUM 5], SUPPRESS+1 [PERFECT_FIT 1], SURVIVOR, TOOLS_OF_THE_TRADE, TOOLS_OF_THE_TRADE+1, ULTIMATE_DEFEND, UNTOUCHABLE+1 [ADROIT 3], WELL_LAID_PLANS+1
- 遗物 21 件：RING_OF_THE_SNAKE, SMALL_CAPSULE, BOWLER_HAT, POCKETWATCH, MINIATURE_CANNON, PEN_NIB(AttacksPlayed=7), ARCHAIC_TOOTH, AMETHYST_AUBERGINE, VAJRA, STRIKE_DUMMY, FAKE_HAPPY_FLOWER(TurnsSeen=1), FAKE_LEES_WAFFLE, PUNCH_DAGGER, SIGNET_RING, HAPPY_FLOWER(TurnsSeen=0), CENTENNIAL_PUZZLE, BRONZE_SCALES, KIFUDA, ETERNAL_FEATHER, TINY_MAILBOX, GAMBLING_CHIP
- 变异：small / cards，改牌 1 改遗物 0，父代 `73af8226bf4d`
- 标签（4 个种子净掉血）：[0, 20, 4, 1] → 均值 **6.2**，组内 std 9.3，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 37.2 (+31.0, 死亡 0.31), repo_mlp 49.0 (+42.7, 死亡 0.48), rtdl_mlp 54.1 (+47.9, 死亡 0.41), rtdl_resnet 56.9 (+50.6, 死亡 0.53), set_transformer 10.4 (+4.1, 死亡 0.00), tabm 61.6 (+55.4, 死亡 0.60), ensemble 44.9 (+38.6, 死亡 0.39)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — mutation / mut-v1 / 构筑 `8a2f6528f432`
- 牌组 21 张：ACROBATICS+1, ASCENDERS_BANE, CALCULATED_GAMBLE+1, DAGGER_THROW, DEFEND_SILENT×5, FLICK_FLACK, NOXIOUS_FUMES, PIERCING_WAIL, PREPARED, PREPARED [ADROIT 3], RICOCHET+1 [MOMENTUM 5], SUPPRESS+1 [PERFECT_FIT 1], SURVIVOR, TOOLS_OF_THE_TRADE, TOOLS_OF_THE_TRADE+1, UNTOUCHABLE+1 [ADROIT 3], WELL_LAID_PLANS+1
- 遗物 20 件：RING_OF_THE_SNAKE, SMALL_CAPSULE, BOWLER_HAT, POCKETWATCH, MINIATURE_CANNON, PEN_NIB(AttacksPlayed=7), ARCHAIC_TOOTH, AMETHYST_AUBERGINE, VAJRA, STRIKE_DUMMY, FAKE_HAPPY_FLOWER(TurnsSeen=1), FAKE_LEES_WAFFLE, PUNCH_DAGGER, SIGNET_RING, CENTENNIAL_PUZZLE, BRONZE_SCALES, KIFUDA, ETERNAL_FEATHER, TINY_MAILBOX, GAMBLING_CHIP
- 变异：small / relics，改牌 0 改遗物 1，父代 `73af8226bf4d`
- 标签（4 个种子净掉血）：[35, 1, 21, 4] → 均值 **15.2**，组内 std 15.8，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 38.6 (+23.4, 死亡 0.30), repo_mlp 49.2 (+33.9, 死亡 0.52), rtdl_mlp 57.3 (+42.0, 死亡 0.52), rtdl_resnet 60.2 (+44.9, 死亡 0.64), set_transformer 12.4 (-2.9, 死亡 0.00), tabm 63.4 (+48.2, 死亡 0.65), ensemble 46.8 (+31.6, 死亡 0.44)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — mutation / mut-v2 / 构筑 `cacbf35256c4`
- 牌组 21 张：ACROBATICS+1, ASCENDERS_BANE, CALCULATED_GAMBLE+1, DAGGER_THROW, DEFEND_SILENT×5, FLICK_FLACK, NOXIOUS_FUMES, PIERCING_WAIL, PREPARED, PREPARED [ADROIT 3], RICOCHET+1 [MOMENTUM 5], SUPPRESS+1 [PERFECT_FIT 1], SURVIVOR, TOOLS_OF_THE_TRADE, TOOLS_OF_THE_TRADE+1, UNTOUCHABLE+1 [ADROIT 3], WELL_LAID_PLANS+1
- 遗物 21 件：RING_OF_THE_SNAKE, SMALL_CAPSULE, BOWLER_HAT, POCKETWATCH, MINIATURE_CANNON, PEN_NIB(AttacksPlayed=7), ARCHAIC_TOOTH, AMETHYST_AUBERGINE, VAJRA, STRIKE_DUMMY, FAKE_HAPPY_FLOWER(TurnsSeen=1), FAKE_LEES_WAFFLE, SIGNET_RING, HAPPY_FLOWER(TurnsSeen=0), CENTENNIAL_PUZZLE, BRONZE_SCALES, KIFUDA, ETERNAL_FEATHER, TINY_MAILBOX, GAMBLING_CHIP, SCREAMING_FLAGON
- 变异：small / relics，改牌 0 改遗物 1，父代 `73af8226bf4d`
- 标签（4 个种子净掉血）：[0, 1, 16, 1] → 均值 **4.5**，组内 std 7.7，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 36.6 (+32.1, 死亡 0.26), repo_mlp 46.7 (+42.2, 死亡 0.37), rtdl_mlp 48.2 (+43.7, 死亡 0.31), rtdl_resnet 54.0 (+49.5, 死亡 0.51), set_transformer 9.1 (+4.6, 死亡 0.00), tabm 59.7 (+55.2, 死亡 0.54), ensemble 42.4 (+37.9, 死亡 0.33)

## 最严重高估（预测 ≫ 标签）

模型认为会掉很多血，实际老师打得轻松。

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — real / real-v4 / 构筑 `c2d37af897f8`
- 牌组 34 张：ACCELERANT+1, ADRENALINE+1 [SOULS_POWER 1]×2, ASCENDERS_BANE, BACKFLIP [NIMBLE 2], BLADE_OF_INK+1, BLUR+1 [NIMBLE 2]×2, BUBBLE_BUBBLE+1, BURST+1, CLUMSY, DECAY, DEFEND_SILENT×2, DEFEND_SILENT+1×2, DEFLECT [NIMBLE 2], DODGE_AND_ROLL [NIMBLE 2], ESCAPE_PLAN [NIMBLE 2], FASTEN+1, FINISHER [STEADY 1], FOOTWORK+1, LEG_SWEEP+1 [NIMBLE 2], NEUTRALIZE+1, NOXIOUS_FUMES, NOXIOUS_FUMES+1 [SWIFT 2], PIERCING_WAIL+1, PREPARED, SHADOWMELD+1, SPLASH+1, SURVIVOR+1, THE_HUNT+1 [STEADY 1], TOOLS_OF_THE_TRADE, ULTIMATE_STRIKE+1
- 遗物 15 件：RING_OF_THE_DRAKE, FRESNEL_LENS, ETERNAL_FEATHER, VAJRA, CAPTAINS_WHEEL, TOUCH_OF_OROBAS, RAINBOW_RING, PERMAFROST, SPARKLING_ROUGE, WAR_HAMMER, DOLLYS_MIRROR, FRAGRANT_MUSHROOM, CLOAK_CLASP, AKABEKO, VEXING_PUZZLEBOX
- 标签（4 个种子净掉血）：[8, 0, 0, 0] → 均值 **2.0**，组内 std 4.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 37.8 (+35.8, 死亡 0.09), repo_mlp 26.5 (+24.5, 死亡 0.08), rtdl_mlp 25.2 (+23.2, 死亡 0.04), rtdl_resnet 23.0 (+21.0, 死亡 0.12), set_transformer 52.7 (+50.7, 死亡 0.52), tabm 31.4 (+29.4, 死亡 0.17), ensemble 32.8 (+30.8, 死亡 0.17)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — mutation / mut-v2 / 构筑 `f1d0984f6767`
- 牌组 35 张：ACCURACY+1, ACROBATICS, ADRENALINE×2, AFTERIMAGE+1 [SWIFT 2], ASCENDERS_BANE, ASSASSINATE, BLADE_DANCE+1, BLADE_OF_INK+1, BURST+1, CLOAK_AND_DAGGER+1, DEFEND_SILENT×3, ESCAPE_PLAN+1, EXPOSE, FAN_OF_KNIVES, HAND_TRICK, HIDDEN_DAGGERS, KNIFE_TRAP, LEADING_STRIKE, NEUTRALIZE, PHANTOM_BLADES+1, PREPARED×2, REFLEX+1, RICOCHET, STORM_OF_STEEL, STRIKE_SILENT [TEZCATARAS_EMBER 1]×4, SURVIVOR, THE_HUNT+1, UP_MY_SLEEVE+1
- 遗物 17 件：RING_OF_THE_SNAKE, NEW_LEAF, WHITE_STAR, POTION_BELT, SPARKLING_ROUGE, NUTRITIOUS_SOUP, TEA_OF_DISCOURTESY(CombatsLeft=1), UNSETTLING_LAMP, LASTING_CANDY(CombatRewardsSeen=2), DAUGHTER_OF_THE_WIND, GHOST_SEED, JEWELED_MASK, CENTENNIAL_PUZZLE, HAPPY_FLOWER(TurnsSeen=0), LANTERN, VAJRA, BAG_OF_MARBLES
- 变异：small / both，改牌 1 改遗物 2，父代 `8551ecfc7295`
- 标签（4 个种子净掉血）：[5, 10, 2, 3] → 均值 **5.0**，组内 std 3.6，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 56.0 (+51.0, 死亡 0.80), repo_mlp 32.8 (+27.8, 死亡 0.20), rtdl_mlp 46.2 (+41.2, 死亡 0.38), rtdl_resnet 54.4 (+49.4, 死亡 0.44), set_transformer 53.0 (+48.0, 死亡 0.50), tabm 56.0 (+51.0, 死亡 0.53), ensemble 49.7 (+44.7, 死亡 0.47)

**OVERGROWTH / BYRDONIS_ELITE** (Elite; 怪物 BYRDONIS) — real / real-v3 / 构筑 `dbf10b62ab94`
- 牌组 17 张：ASCENDERS_BANE, DEFEND_SILENT×5, DODGE_AND_ROLL [NIMBLE 2], GRAND_FINALE, INJURY, NEUTRALIZE, PREPARED, STRIKE_SILENT×3, SURVIVOR, THE_HUNT, UNTOUCHABLE
- 遗物 2 件：RING_OF_THE_SNAKE, HEFTY_TABLET
- 标签（4 个种子净掉血）：[5, 23, 4, 10] → 均值 **10.5**，组内 std 8.7，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 44.0 (+33.5, 死亡 0.22), repo_mlp 60.5 (+50.0, 死亡 0.67), rtdl_mlp 62.6 (+52.1, 死亡 0.51), rtdl_resnet 63.4 (+52.9, 死亡 0.64), set_transformer 57.9 (+47.4, 死亡 0.27), tabm 59.3 (+48.8, 死亡 0.33), ensemble 57.9 (+47.4, 死亡 0.44)

**GLORY / QUEEN_BOSS** (Boss; 怪物 QUEEN, TORCH_HEAD_AMALGAM) — mutation / mut-v1 / 构筑 `c2853bdf7914`
- 牌组 36 张：AFTERIMAGE+1, ASCENDERS_BANE, BACKFLIP×2, BACKSTAB+1, BLADE_OF_INK+1, BOUNCING_FLASK+1 [SLITHER 1], CLOAK_AND_DAGGER, CLOAK_AND_DAGGER+1×2, CLUMSY, DEFEND_SILENT×5, DOUBT, EXPOSE, FINESSE, FOOTWORK, HAZE+1, INFINITE_BLADES, LEADING_STRIKE×3, NEUTRALIZE+1, NOXIOUS_FUMES, PIERCING_WAIL, POISONED_STAB, STRIKE_SILENT, STRIKE_SILENT+1×2, SURVIVOR, TOOLS_OF_THE_TRADE+1, ULTIMATE_STRIKE, UNTOUCHABLE+1
- 遗物 16 件：RING_OF_THE_SNAKE, KUNAI, WHETSTONE, VEXING_PUZZLEBOX, LANTERN, YUMMY_COOKIE, GAME_PIECE, ODDLY_SMOOTH_STONE, PARRYING_SHIELD, VENERABLE_TEA_SET(GainEnergyInNextCombat=True), MUSIC_BOX, AMETHYST_AUBERGINE, FORGOTTEN_SOUL, HAPPY_FLOWER(TurnsSeen=1), PANTOGRAPH, STURDY_CLAMP
- 变异：small / relics，改牌 0 改遗物 1，父代 `6d9c4378bd83`
- 标签（4 个种子净掉血）：[19, 25, 35, 0] → 均值 **19.8**，组内 std 14.7，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 51.3 (+31.6, 死亡 0.23), repo_mlp 64.6 (+44.9, 死亡 0.70), rtdl_mlp 57.3 (+37.6, 死亡 0.48), rtdl_resnet 57.1 (+37.3, 死亡 0.49), set_transformer 64.3 (+44.5, 死亡 0.72), tabm 54.0 (+34.2, 死亡 0.35), ensemble 58.1 (+38.4, 死亡 0.50)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — real / real-v4 / 构筑 `93f77f84bf5b`
- 牌组 33 张：ADRENALINE+1, ASCENDERS_BANE, ASSASSINATE, BLUR, BLUR [NIMBLE 2], CALCULATED_GAMBLE×2, DEADLY_POISON×3, DEADLY_POISON+1, DEFEND_SILENT×4, DEFEND_SILENT [SPIRAL 1], ECHOING_SLASH, ESCAPE_PLAN, FASTEN+1, MAUL×6, NEUTRALIZE, NOXIOUS_FUMES, NOXIOUS_FUMES+1×2, PIERCING_WAIL+1, SIDESTEP, ULTIMATE_DEFEND, WELL_LAID_PLANS
- 遗物 17 件：RING_OF_THE_SNAKE, BOOMING_CONCH, RIPPLE_BASIN, MUMMIFIED_HAND, CENTENNIAL_PUZZLE, AKABEKO, PAELS_TEARS, TOOLBOX, GIRYA(TimesLifted=1), REGAL_PILLOW, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), CLAWS, ODDLY_SMOOTH_STONE, FRAGRANT_MUSHROOM, RED_MASK, BRONZE_SCALES, BLOOD_VIAL
- 标签（4 个种子净掉血）：[17, 8, 58, 21] → 均值 **26.0**，组内 std 22.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 51.6 (+25.6, 死亡 0.45), repo_mlp 59.3 (+33.3, 死亡 0.49), rtdl_mlp 59.1 (+33.1, 死亡 0.43), rtdl_resnet 66.0 (+40.0, 死亡 0.77), set_transformer 68.7 (+42.7, 死亡 0.89), tabm 62.8 (+36.8, 死亡 0.63), ensemble 61.3 (+35.3, 死亡 0.61)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — mutation / mut-v2 / 构筑 `904a900a7777`
- 牌组 40 张：ADRENALINE+1, ASCENDERS_BANE, ASSASSINATE+1, BACKFLIP, BACKFLIP+1, BACKSTAB+1, CALCULATED_GAMBLE+1×2, CLUMSY, DASH, DEFEND_SILENT×5, DEFLECT, EXPOSE, FOOTWORK+1, GOLD_AXE+1, INFINITE_BLADES+1 [SWIFT 2], LEG_SWEEP+1, MAYHEM+1, NEUTRALIZE+1, NOXIOUS_FUMES+1, PHANTOM_BLADES×2, PREPARED+1, RICOCHET+1, SHADOW_STEP+1, SNAKEBITE, STRIKE_SILENT×2, STRIKE_SILENT+1×2, SURVIVOR, TACTICIAN+1, ULTIMATE_STRIKE+1, WISH×3
- 遗物 16 件：RING_OF_THE_SNAKE, WINGED_BOOTS(TimesUsed=0), VAJRA, AKABEKO, BRONZE_SCALES, PAELS_FLESH, WAR_PAINT, DAUGHTER_OF_THE_WIND, RIPPLE_BASIN, WHETSTONE, KUSARIGAMA, RAINBOW_RING, ANCHOR, LETTER_OPENER, FAKE_LEES_WAFFLE, PERMAFROST
- 变异：large / cards，改牌 3 改遗物 0，父代 `89fd267f6c8b`
- 标签（4 个种子净掉血）：[41, 8, 23, 0] → 均值 **18.0**，组内 std 18.1，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 41.0 (+23.0, 死亡 0.20), repo_mlp 41.2 (+23.2, 死亡 0.20), rtdl_mlp 48.7 (+30.7, 死亡 0.30), rtdl_resnet 55.5 (+37.5, 死亡 0.50), set_transformer 60.0 (+42.0, 死亡 0.65), tabm 50.6 (+32.6, 死亡 0.37), ensemble 49.5 (+31.5, 死亡 0.37)

**GLORY / QUEEN_BOSS** (Boss; 怪物 QUEEN, TORCH_HEAD_AMALGAM) — mutation / mut-v2 / 构筑 `0735f04c6213`
- 牌组 35 张：ABRASIVE, ACCELERANT, ACCURACY+1, AFTERIMAGE+1, ANTICIPATE+1, ASCENDERS_BANE, BACKFLIP, BLADE_DANCE, DEFEND_SILENT×5, DEFLECT+1, ENVENOM+1, FAN_OF_KNIVES, FINESSE, FOOTWORK+1×3, HAND_TRICK, HIDDEN_DAGGERS, KNIFE_TRAP, MAD_SCIENCE+1 {TinkerTimeRider=8,TinkerTimeType=3}, NEUTRALIZE+1, NOXIOUS_FUMES, PHANTOM_BLADES+1, PIERCING_WAIL×2, SERPENT_FORM+1, SNAKEBITE+1×2, STORM_OF_STEEL, SURVIVOR, WELL_LAID_PLANS+1
- 遗物 16 件：RING_OF_THE_SNAKE, WINGED_BOOTS(TimesUsed=1), BRONZE_SCALES, TOUGH_BANDAGES, RED_MASK, BLOOD_VIAL, YUMMY_COOKIE, POLLINOUS_CORE(TurnsSeen=3), JOSS_PAPER(CardsExhausted=4), FESTIVE_POPPER, CENTENNIAL_PUZZLE, REGAL_PILLOW, SNECKO_SKULL, HAPPY_FLOWER(TurnsSeen=0), WING_CHARM, LAVA_LAMP(TookDamageThisCombat=False)
- 变异：small / relics，改牌 0 改遗物 2，父代 `0cfe0e57ded2`
- 标签（4 个种子净掉血）：[3, 10, 11, 15] → 均值 **9.8**，组内 std 5.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 37.7 (+28.0, 死亡 0.07), repo_mlp 51.7 (+42.0, 死亡 0.25), rtdl_mlp 37.5 (+27.7, 死亡 0.10), rtdl_resnet 42.5 (+32.8, 死亡 0.13), set_transformer 51.2 (+41.4, 死亡 0.21), tabm 43.4 (+33.7, 死亡 0.13), ensemble 44.0 (+34.3, 死亡 0.15)

**GLORY / QUEEN_BOSS** (Boss; 怪物 QUEEN, TORCH_HEAD_AMALGAM) — real / real-v4 / 构筑 `0cfe0e57ded2`
- 牌组 35 张：ABRASIVE, ACCELERANT, ACCURACY+1, AFTERIMAGE+1, ANTICIPATE+1, ASCENDERS_BANE, BACKFLIP, BLADE_DANCE, DEFEND_SILENT×5, DEFLECT+1, ENVENOM+1, FAN_OF_KNIVES, FINESSE, FOOTWORK+1×3, HAND_TRICK, HIDDEN_DAGGERS, KNIFE_TRAP, MAD_SCIENCE+1 {TinkerTimeRider=8,TinkerTimeType=3}, NEUTRALIZE+1, NOXIOUS_FUMES, PHANTOM_BLADES+1, PIERCING_WAIL×2, SERPENT_FORM+1, SNAKEBITE+1×2, STORM_OF_STEEL, SURVIVOR, WELL_LAID_PLANS+1
- 遗物 15 件：RING_OF_THE_SNAKE, WINGED_BOOTS(TimesUsed=1), BRONZE_SCALES, WHITE_STAR, TOUGH_BANDAGES, RED_MASK, BLOOD_VIAL, YUMMY_COOKIE, POLLINOUS_CORE(TurnsSeen=3), JOSS_PAPER(CardsExhausted=4), FESTIVE_POPPER, CENTENNIAL_PUZZLE, REGAL_PILLOW, SNECKO_SKULL, HAPPY_FLOWER(TurnsSeen=0)
- 标签（4 个种子净掉血）：[3, 10, 11, 15] → 均值 **9.8**，组内 std 5.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 35.1 (+25.3, 死亡 0.06), repo_mlp 48.9 (+39.1, 死亡 0.20), rtdl_mlp 40.3 (+30.6, 死亡 0.18), rtdl_resnet 43.9 (+34.2, 死亡 0.09), set_transformer 49.8 (+40.0, 死亡 0.18), tabm 43.6 (+33.8, 死亡 0.13), ensemble 43.6 (+33.8, 死亡 0.14)

## 最严重低估（预测 ≪ 标签）

模型认为安全，实际老师掉血多或死亡。

**HIVE / OVICOPTER_NORMAL** (Monster; 怪物 OVICOPTER, TOUGH_EGG) — real / real-v4 / 构筑 `5a6cb0ef23c6`
- 牌组 19 张：ASCENDERS_BANE, BLADE_DANCE+1, DEADLY_POISON+1, DEFEND_SILENT×4, DEFEND_SILENT+1, ESCAPE_PLAN, HIDDEN_DAGGERS+1, LEADING_STRIKE+1 [GLAM 1], NEUTRALIZE+1, PREPARED+1, STRIKE_SILENT×4, SURVIVOR [NIMBLE 2], WELL_LAID_PLANS+1
- 遗物 5 件：RING_OF_THE_SNAKE, SILKEN_TRESS(IsUsed=True), ANCHOR, GAME_PIECE, PENDULUM(TurnsSeen=0)
- 标签（4 个种子净掉血）：[46, 70, 70, 70] → 均值 **64.0**，组内 std 12.0，死亡 3/4
- 预测（误差，死亡概率）：lightgbm 20.7 (-43.3, 死亡 0.06), repo_mlp 22.4 (-41.6, 死亡 0.02), rtdl_mlp 13.2 (-50.8, 死亡 0.00), rtdl_resnet 33.2 (-30.8, 死亡 0.12), set_transformer 13.8 (-50.2, 死亡 0.01), tabm 26.8 (-37.2, 死亡 0.06), ensemble 21.7 (-42.3, 死亡 0.04)

**GLORY / KNIGHTS_ELITE** (Elite; 怪物 FLAIL_KNIGHT, SPECTRAL_KNIGHT, MAGI_KNIGHT) — mutation / targeted-v1 / 构筑 `621aefc0a289`
- 牌组 25 张：ABRASIVE, ACCELERANT+1, ASCENDERS_BANE, ASSASSINATE, BURST+1, CLUMSY, DAGGER_SPRAY, DEADLY_POISON+1×2, DEFEND_SILENT×5, DODGE_AND_ROLL, FOOTWORK, FOOTWORK+1, NEUTRALIZE+1 [SHARP 2], PIERCING_WAIL, SLICE, SNAKEBITE+1, STRIKE_SILENT×2, TACTICIAN, TACTICIAN+1
- 遗物 19 件：RING_OF_THE_SNAKE, LAVA_ROCK(HasTriggered=True), HAND_DRILL, POTION_BELT, LANTERN, HAPPY_FLOWER(TurnsSeen=0), AMETHYST_AUBERGINE, RUNIC_PYRAMID, PERMAFROST, LETTER_OPENER, FESTIVE_POPPER, SPARKLING_ROUGE, MEAL_TICKET, SAI, ODDLY_SMOOTH_STONE, FAKE_ANCHOR, BLOOD_VIAL, ORICHALCUM, CHEMICAL_X
- 变异：small / both，改牌 2 改遗物 1，父代 `3cff98042167`
- 标签（4 个种子净掉血）：[70, 43, 70, 47] → 均值 **57.5**，组内 std 14.5，死亡 2/4
- 预测（误差，死亡概率）：lightgbm 19.7 (-37.8, 死亡 0.01), repo_mlp 15.0 (-42.5, 死亡 0.00), rtdl_mlp 24.0 (-33.5, 死亡 0.00), rtdl_resnet 14.5 (-43.0, 死亡 0.00), set_transformer 12.9 (-44.6, 死亡 0.01), tabm 23.1 (-34.4, 死亡 0.03), ensemble 18.2 (-39.3, 死亡 0.01)

**GLORY / THE_LOST_AND_FORGOTTEN_NORMAL** (Monster; 怪物 THE_LOST, THE_FORGOTTEN) — real / real-v3 / 构筑 `b716d1505a8f`
- 牌组 31 张：ACROBATICS, ADRENALINE [SOULS_POWER 1], AFTERIMAGE+1, ASCENDERS_BANE, ASSASSINATE+1, CLOAK_AND_DAGGER×2, DECAY, DEFEND_SILENT×5, DODGE_AND_ROLL, EXPOSE, FAN_OF_KNIVES, FOOTWORK+1, HIDDEN_DAGGERS, INFINITE_BLADES+1, KNIFE_TRAP, LEG_SWEEP, STRIKE_SILENT×4, SUPPRESS+1, SURVIVOR, TORIC_TOUGHNESS, UNTOUCHABLE×2, UP_MY_SLEEVE
- 遗物 12 件：RING_OF_THE_SNAKE, HEFTY_TABLET, PLANISPHERE, PERMAFROST, JOSS_PAPER(CardsExhausted=2), ARCHAIC_TOOTH, GORGET, ODDLY_SMOOTH_STONE, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), BEATING_REMNANT, SNECKO_SKULL, IRON_CLUB(CardsPlayed=3)
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 14.2 (-55.8, 死亡 0.00), repo_mlp 26.1 (-43.9, 死亡 0.02), rtdl_mlp 14.4 (-55.6, 死亡 0.00), rtdl_resnet 19.7 (-50.3, 死亡 0.01), set_transformer 25.5 (-44.5, 死亡 0.06), tabm 9.8 (-60.2, 死亡 0.00), ensemble 18.3 (-51.7, 死亡 0.02)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — real / real-v4 / 构筑 `2bdd4e121d81`
- 牌组 27 张：ACROBATICS+1, ASCENDERS_BANE, BACKFLIP [NIMBLE 2], BACKFLIP+1 [NIMBLE 2], BLADE_DANCE+1, BLADE_OF_INK+1, BLUR, BLUR [NIMBLE 2], CALCULATED_GAMBLE+1, CLUMSY, DEFEND_SILENT, DEFEND_SILENT [SPIRAL 1], DEFLECT [NIMBLE 2], EXPOSE+1, LEADING_STRIKE, NEOWS_FURY+1, NEUTRALIZE+1, NOXIOUS_FUMES+1, PHANTOM_BLADES, STRIKE_SILENT [TEZCATARAS_EMBER 1]×3, STRIKE_SILENT+1 [TEZCATARAS_EMBER 1]×2, SURVIVOR [NIMBLE 2], THE_GAMBIT+1 [NIMBLE 2], TOOLS_OF_THE_TRADE+1
- 遗物 17 件：RING_OF_THE_SNAKE, NEOWS_TORMENT, BELLOWS, FRESNEL_LENS, MINIATURE_CANNON, NUTRITIOUS_SOUP, DAUGHTER_OF_THE_WIND, LANTERN, RAZOR_TOOTH, VAMBRACE, MUSIC_BOX, FRAGRANT_MUSHROOM, ART_OF_WAR, BAG_OF_PREPARATION, GAME_PIECE, THE_COURIER, BRONZE_SCALES
- 标签（4 个种子净掉血）：[40, 70, 70, 70] → 均值 **62.5**，组内 std 15.0，死亡 3/4
- 预测（误差，死亡概率）：lightgbm 45.8 (-16.7, 死亡 0.44), repo_mlp 54.4 (-8.1, 死亡 0.52), rtdl_mlp 58.3 (-4.2, 死亡 0.56), rtdl_resnet 32.1 (-30.4, 死亡 0.18), set_transformer 18.6 (-43.9, 死亡 0.09), tabm 62.3 (-0.2, 死亡 0.74), ensemble 45.3 (-17.2, 死亡 0.42)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — mutation / mut-v2 / 构筑 `d1cb9c1da772`
- 牌组 33 张：ASCENDERS_BANE, BACKFLIP, BUBBLE_BUBBLE, CALCULATED_GAMBLE+1 [SOULS_POWER 1], CLOAK_AND_DAGGER, DEFEND_SILENT×4, DEFLECT, ESCAPE_PLAN, FLICK_FLACK [INSTINCT 1], FOOTWORK, HAND_TRICK, LEADING_STRIKE+1, LEG_SWEEP, NEUTRALIZE+1 [INSTINCT 1], PIERCING_WAIL, PREPARED, PREPARED+1, REFLEX+1, RICOCHET+1 [INSTINCT 1], RICOCHET+1 [SHARP 2], SIDESTEP, SNAKEBITE, STRIKE_SILENT, STRIKE_SILENT+1, SURVIVOR+1, TACTICIAN, TOOLS_OF_THE_TRADE, UNTOUCHABLE, UNTOUCHABLE+1, WELL_LAID_PLANS
- 遗物 20 件：RING_OF_THE_SNAKE, SCROLL_BOXES, SPARKLING_ROUGE, OLD_COIN, POTION_BELT, RINGING_TRIANGLE, WAR_PAINT, AMETHYST_AUBERGINE, TOASTY_MITTENS, UNSETTLING_LAMP, PENDULUM(TurnsSeen=0), WHETSTONE, TRI_BOOMERANG, POCKETWATCH, MINIATURE_CANNON, CHANDELIER, BRONZE_SCALES, GAME_PIECE, PAPER_KRANE, VENERABLE_TEA_SET(GainEnergyInNextCombat=True)
- 变异：large / relics，改牌 0 改遗物 3，父代 `f9bb15224cf1`
- 标签（4 个种子净掉血）：[70, 50, 60, 45] → 均值 **56.2**，组内 std 11.1，死亡 1/4
- 预测（误差，死亡概率）：lightgbm 55.3 (-1.0, 死亡 0.48), repo_mlp 50.9 (-5.3, 死亡 0.41), rtdl_mlp 44.0 (-12.3, 死亡 0.26), rtdl_resnet 62.5 (+6.3, 死亡 0.76), set_transformer 12.6 (-43.6, 死亡 0.01), tabm 55.3 (-1.0, 死亡 0.50), ensemble 46.8 (-9.5, 死亡 0.40)

**UNDERDOCKS / LAGAVULIN_MATRIARCH_BOSS** (Boss; 怪物 LAGAVULIN_MATRIARCH) — real / real-v3 / 构筑 `a9dadd25c89b`
- 牌组 19 张：ASCENDERS_BANE, BLADE_DANCE+1, CLOAK_AND_DAGGER+1, DEFEND_SILENT×4, ESCAPE_PLAN, INFINITE_BLADES, LEADING_STRIKE, NEUTRALIZE, PHANTOM_BLADES+1, PREPARED+1, STRIKE_SILENT×4, SURVIVOR [NIMBLE 2], TACTICIAN
- 遗物 7 件：RING_OF_THE_SNAKE, NEOWS_BONES, SILVER_CRUCIBLE(TimesUsed=3,TreasureRoomsEntered=0), PRECARIOUS_SHEARS, CLOAK_CLASP, SNECKO_SKULL, AKABEKO
- 标签（4 个种子净掉血）：[70, 70, 70, 69] → 均值 **69.8**，组内 std 0.5，死亡 3/4
- 预测（误差，死亡概率）：lightgbm 45.1 (-24.7, 死亡 0.55), repo_mlp 32.5 (-37.2, 死亡 0.08), rtdl_mlp 41.1 (-28.6, 死亡 0.25), rtdl_resnet 28.1 (-41.7, 死亡 0.03), set_transformer 27.1 (-42.7, 死亡 0.06), tabm 46.0 (-23.8, 死亡 0.27), ensemble 36.6 (-33.1, 死亡 0.21)

**GLORY / QUEEN_BOSS** (Boss; 怪物 QUEEN, TORCH_HEAD_AMALGAM) — real / real-v4 / 构筑 `2bdd4e121d81`
- 牌组 27 张：ACROBATICS+1, ASCENDERS_BANE, BACKFLIP [NIMBLE 2], BACKFLIP+1 [NIMBLE 2], BLADE_DANCE+1, BLADE_OF_INK+1, BLUR, BLUR [NIMBLE 2], CALCULATED_GAMBLE+1, CLUMSY, DEFEND_SILENT, DEFEND_SILENT [SPIRAL 1], DEFLECT [NIMBLE 2], EXPOSE+1, LEADING_STRIKE, NEOWS_FURY+1, NEUTRALIZE+1, NOXIOUS_FUMES+1, PHANTOM_BLADES, STRIKE_SILENT [TEZCATARAS_EMBER 1]×3, STRIKE_SILENT+1 [TEZCATARAS_EMBER 1]×2, SURVIVOR [NIMBLE 2], THE_GAMBIT+1 [NIMBLE 2], TOOLS_OF_THE_TRADE+1
- 遗物 17 件：RING_OF_THE_SNAKE, NEOWS_TORMENT, BELLOWS, FRESNEL_LENS, MINIATURE_CANNON, NUTRITIOUS_SOUP, DAUGHTER_OF_THE_WIND, LANTERN, RAZOR_TOOTH, VAMBRACE, MUSIC_BOX, FRAGRANT_MUSHROOM, ART_OF_WAR, BAG_OF_PREPARATION, GAME_PIECE, THE_COURIER, BRONZE_SCALES
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 50.2 (-19.8, 死亡 0.46), repo_mlp 54.7 (-15.3, 死亡 0.40), rtdl_mlp 52.7 (-17.3, 死亡 0.28), rtdl_resnet 29.7 (-40.3, 死亡 0.15), set_transformer 28.7 (-41.3, 死亡 0.09), tabm 56.5 (-13.5, 死亡 0.52), ensemble 45.4 (-24.6, 死亡 0.32)

**HIVE / THE_INSATIABLE_BOSS** (Boss; 怪物 THE_INSATIABLE) — mutation / mut-v2 / 构筑 `ae2d01d5adc6`
- 牌组 24 张：ASCENDERS_BANE, CORROSIVE_WAVE+1, DAGGER_SPRAY+1, DAGGER_THROW+1, DASH, DEFEND_SILENT×5, DEFLECT, ECHOING_SLASH+1, EXPOSE+1, FISTICUFFS+1, NEUTRALIZE+1, PINPOINT+1, PRECISE_CUT+1, PREPARED, PREPARED+1, RICOCHET+1, STRIKE_SILENT×2, SURVIVOR, WELL_LAID_PLANS+1
- 遗物 8 件：RING_OF_THE_SNAKE, LEAD_PAPERWEIGHT, PARRYING_SHIELD, MOLTEN_EGG, HAPPY_FLOWER(TurnsSeen=0), BONE_TEA(CombatsLeft=1), ANCHOR, PANTOGRAPH
- 变异：large / cards，改牌 3 改遗物 0，父代 `babdd8edde44`
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 52.6 (-17.4, 死亡 0.50), repo_mlp 47.2 (-22.8, 死亡 0.29), rtdl_mlp 50.4 (-19.6, 死亡 0.40), rtdl_resnet 42.4 (-27.6, 死亡 0.26), set_transformer 29.0 (-41.0, 死亡 0.12), tabm 55.8 (-14.2, 死亡 0.52), ensemble 46.2 (-23.8, 死亡 0.35)

## 高掉血但预测准确

标签均值 ≥ 25 HP 且 |误差| ≤ 2 HP 的 pair。

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — mutation / mut-v2 / 构筑 `54d745895387`
- 牌组 36 张：ACCURACY, ACROBATICS, ASCENDERS_BANE, BACKFLIP, BLADE_DANCE, BUBBLE_BUBBLE+1, CLOAK_AND_DAGGER, DAGGER_SPRAY, DEFEND_SILENT×2, DEFEND_SILENT+1×2, DODGE_AND_ROLL×3, ENVENOM, ESCAPE_PLAN+1, FOOTWORK, FOOTWORK+1, HIDDEN_DAGGERS, LEADING_STRIKE, MASTER_PLANNER, MIRAGE, NEUTRALIZE+1, POUNCE+1, SNAKEBITE+1, STRIKE_SILENT×2, STRIKE_SILENT+1×2, SURVIVOR+1, THE_HUNT, TOOLS_OF_THE_TRADE+1, UNTOUCHABLE+1×2, UP_MY_SLEEVE
- 遗物 17 件：RING_OF_THE_SNAKE, STRIKE_DUMMY, SPARKLING_ROUGE, BLOOD_VIAL, RED_MASK, SNECKO_SKULL, SAND_CASTLE, MR_STRUGGLES, MERCURY_HOURGLASS, UNSETTLING_LAMP, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), REGAL_PILLOW, FAKE_BLOOD_VIAL, FAKE_VENERABLE_TEA_SET(GainEnergyInNextCombat=True), ANCHOR, BRONZE_SCALES, LANTERN
- 变异：large / cards，改牌 5 改遗物 0，父代 `d29b320aa2b8`
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 67.9 (-2.1, 死亡 0.71), repo_mlp 65.9 (-4.1, 死亡 0.84), rtdl_mlp 67.1 (-2.9, 死亡 0.94), rtdl_resnet 67.5 (-2.5, 死亡 0.99), set_transformer 70.0 (+0.0, 死亡 0.98), tabm 69.8 (-0.2, 死亡 0.93), ensemble 68.0 (-2.0, 死亡 0.90)

**UNDERDOCKS / SKULKING_COLONY_ELITE** (Elite; 怪物 SKULKING_COLONY) — real / real-v4 / 构筑 `ab35d9485c4f`
- 牌组 16 张：ASCENDERS_BANE, CLOAK_AND_DAGGER [NIMBLE 2], DEFEND_SILENT×5, LEADING_STRIKE, NEUTRALIZE, NOXIOUS_FUMES, STRIKE_SILENT×5, SURVIVOR
- 遗物 4 件：RING_OF_THE_SNAKE, SMALL_CAPSULE, TINY_MAILBOX, POTION_BELT
- 标签（4 个种子净掉血）：[26, 21, 25, 39] → 均值 **27.8**，组内 std 7.8，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 27.0 (-0.8, 死亡 0.00), repo_mlp 20.8 (-7.0, 死亡 0.00), rtdl_mlp 23.4 (-4.3, 死亡 0.00), rtdl_resnet 25.9 (-1.9, 死亡 0.00), set_transformer 27.3 (-0.4, 死亡 0.00), tabm 26.4 (-1.4, 死亡 0.00), ensemble 25.1 (-2.6, 死亡 0.00)

**UNDERDOCKS / PHANTASMAL_GARDENERS_ELITE** (Elite; 怪物 PHANTASMAL_GARDENER) — real / real-v3 / 构筑 `04078c6c97a5`
- 牌组 17 张：ASCENDERS_BANE, ASSASSINATE, DAGGER_THROW, DEFEND_SILENT×4, INFINITE_BLADES, LEADING_STRIKE, MASTER_PLANNER, NEUTRALIZE, PREPARED, STRIKE_SILENT×4, SURVIVOR
- 遗物 1 件：RING_OF_THE_SNAKE
- 标签（4 个种子净掉血）：[58, 68, 70, 70] → 均值 **66.5**，组内 std 5.7，死亡 2/4
- 预测（误差，死亡概率）：lightgbm 53.8 (-12.7, 死亡 0.49), repo_mlp 51.6 (-14.9, 死亡 0.12), rtdl_mlp 65.1 (-1.4, 死亡 0.66), rtdl_resnet 64.7 (-1.8, 死亡 0.66), set_transformer 66.3 (-0.2, 死亡 0.65), tabm 61.8 (-4.7, 死亡 0.41), ensemble 60.5 (-6.0, 死亡 0.50)

**UNDERDOCKS / WATERFALL_GIANT_BOSS** (Boss; 怪物 WATERFALL_GIANT) — real / real-v4 / 构筑 `07a62be35b2b`
- 牌组 21 张：ASCENDERS_BANE, BACKFLIP, CLUMSY, DEADLY_POISON+1, DEFEND_SILENT×5, DEFLECT [NIMBLE 2], DODGE_AND_ROLL [NIMBLE 2], MIRAGE, NEUTRALIZE, POISONED_STAB+1 [GLAM 1], RICOCHET, STRIKE_SILENT×5, SURVIVOR
- 遗物 6 件：RING_OF_THE_SNAKE, SILKEN_TRESS(IsUsed=True), FRESNEL_LENS, ANCHOR, FESTIVE_POPPER, LUCKY_FYSH
- 标签（4 个种子净掉血）：[43, 32, 25, 44] → 均值 **36.0**，组内 std 9.1，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 45.1 (+9.1, 死亡 0.15), repo_mlp 44.1 (+8.1, 死亡 0.06), rtdl_mlp 43.2 (+7.2, 死亡 0.02), rtdl_resnet 36.0 (+0.0, 死亡 0.00), set_transformer 37.0 (+1.0, 死亡 0.01), tabm 40.6 (+4.6, 死亡 0.06), ensemble 41.0 (+5.0, 死亡 0.05)

**OVERGROWTH / BYGONE_EFFIGY_ELITE** (Elite; 怪物 BYGONE_EFFIGY) — real / real-v3 / 构筑 `a5913b9f553d`
- 牌组 16 张：ASCENDERS_BANE, DEFEND_SILENT×5, DEFLECT, NEUTRALIZE, SKEWER [SHARP 2], SLICE, STRIKE_SILENT×5, SURVIVOR
- 遗物 2 件：RING_OF_THE_SNAKE, WINGED_BOOTS(TimesUsed=2)
- 标签（4 个种子净掉血）：[63, 31, 42, 41] → 均值 **44.2**，组内 std 13.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 54.8 (+10.5, 死亡 0.10), repo_mlp 48.9 (+4.6, 死亡 0.01), rtdl_mlp 54.7 (+10.4, 死亡 0.04), rtdl_resnet 42.7 (-1.5, 死亡 0.00), set_transformer 45.3 (+1.0, 死亡 0.01), tabm 46.9 (+2.7, 死亡 0.05), ensemble 48.9 (+4.6, 死亡 0.03)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — mutation / targeted-v1 / 构筑 `1aa17004f715`
- 牌组 34 张：ABRASIVE, ADRENALINE+1, AFTERIMAGE+1 [SWIFT 2], ASCENDERS_BANE, BACKFLIP+1, BOUNCING_FLASK+1, DEFEND_SILENT×5, DEFLECT, FOOTWORK×2, HAND_TRICK, HAZE+1, IMPATIENCE+1, LEG_SWEEP, MALAISE, NOXIOUS_FUMES+1, OMNISLICE, PIERCING_WAIL, PREDATOR+1, PREPARED×2, SERPENT_FORM+1, SNAKEBITE [SOWN 1], STRIKE_SILENT [TEZCATARAS_EMBER 1]×5, STRIKE_SILENT+1 [TEZCATARAS_EMBER 1], SURVIVOR
- 遗物 14 件：RING_OF_THE_SNAKE, LARGE_CAPSULE, REGAL_PILLOW, POTION_BELT, BAG_OF_PREPARATION, JUZU_BRACELET, MEAL_TICKET, NUTRITIOUS_SOUP, CENTENNIAL_PUZZLE, CROSSBOW, FRAGRANT_MUSHROOM, BRONZE_SCALES, RAZOR_TOOTH, VENERABLE_TEA_SET(GainEnergyInNextCombat=True)
- 变异：large / both，改牌 6 改遗物 2，父代 `5de7a074fa9b`
- 标签（4 个种子净掉血）：[69, 59, 70, 70] → 均值 **67.0**，组内 std 5.4，死亡 2/4
- 预测（误差，死亡概率）：lightgbm 60.9 (-6.1, 死亡 0.55), repo_mlp 70.0 (+3.0, 死亡 0.91), rtdl_mlp 61.6 (-5.4, 死亡 0.75), rtdl_resnet 66.4 (-0.6, 死亡 0.95), set_transformer 66.9 (-0.1, 死亡 0.82), tabm 63.4 (-3.6, 死亡 0.67), ensemble 64.9 (-2.1, 死亡 0.78)

**GLORY / SOUL_NEXUS_ELITE** (Elite; 怪物 SOUL_NEXUS) — mutation / mut-v2 / 构筑 `7d55fcf8ae89`
- 牌组 28 张：ACCELERANT+1×2, ASCENDERS_BANE, BACKFLIP, BUBBLE_BUBBLE, DEADLY_POISON×3, DEADLY_POISON+1, DEFEND_SILENT×5, DEFLECT, EXTERMINATE, FASTEN+1, FLECHETTES, FOOTWORK, FOOTWORK+1, GREED, NEUTRALIZE, NOXIOUS_FUMES+1, PREPARED, RICOCHET+1, SIDESTEP, SURVIVOR, WELL_LAID_PLANS+1
- 遗物 13 件：RING_OF_THE_SNAKE, LAVA_ROCK(HasTriggered=True), SNECKO_SKULL, LETTER_OPENER, POTION_BELT, STRIKE_DUMMY, BIIIG_HUG, LANTERN, LASTING_CANDY(CombatRewardsSeen=1), PEN_NIB(AttacksPlayed=7), MR_STRUGGLES, JEWELED_MASK, GAMBLING_CHIP
- 变异：small / relics，改牌 0 改遗物 2，父代 `ea6fe0eb8f46`
- 标签（4 个种子净掉血）：[31, 37, 36, 35] → 均值 **34.8**，组内 std 2.6，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 19.9 (-14.8, 死亡 0.00), repo_mlp 28.7 (-6.0, 死亡 0.00), rtdl_mlp 16.4 (-18.3, 死亡 0.00), rtdl_resnet 28.5 (-6.2, 死亡 0.00), set_transformer 34.0 (-0.7, 死亡 0.01), tabm 24.8 (-10.0, 死亡 0.00), ensemble 25.4 (-9.4, 死亡 0.00)

**HIVE / KNOWLEDGE_DEMON_BOSS** (Boss; 怪物 KNOWLEDGE_DEMON) — real / real-v3 / 构筑 `178c501356d3`
- 牌组 28 张：ACROBATICS, ASCENDERS_BANE, BACKFLIP, BUBBLE_BUBBLE+1, CLOAK_AND_DAGGER [NIMBLE 2], DEFEND_SILENT×5, ENVENOM, FLASH_OF_STEEL, FOOTWORK, HAZE+1, HIDDEN_DAGGERS, LEADING_STRIKE, LEG_SWEEP, NEUTRALIZE, PIERCING_WAIL, POISONED_STAB, PREDATOR, RELAX×2, STRIKE_SILENT×3, SURVIVOR, TACTICIAN
- 遗物 15 件：RING_OF_THE_SNAKE, LAVA_ROCK(HasTriggered=True), REGAL_PILLOW, VENERABLE_TEA_SET(GainEnergyInNextCombat=True), LANTERN, SNECKO_SKULL, RAINBOW_RING, BOOK_OF_FIVE_RINGS(CardsAdded=1), PAELS_HORN, POLLINOUS_CORE(TurnsSeen=0), BAG_OF_PREPARATION, ODDLY_SMOOTH_STONE, HAPPY_FLOWER(TurnsSeen=0), FESTIVE_POPPER, STONE_CRACKER
- 标签（4 个种子净掉血）：[13, 49, 25, 54] → 均值 **35.2**，组内 std 19.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 29.0 (-6.2, 死亡 0.07), repo_mlp 22.3 (-12.9, 死亡 0.02), rtdl_mlp 12.2 (-23.1, 死亡 0.00), rtdl_resnet 27.6 (-7.6, 死亡 0.10), set_transformer 35.6 (+0.3, 死亡 0.17), tabm 32.3 (-2.9, 死亡 0.11), ensemble 26.5 (-8.7, 死亡 0.08)

## 随机典型样例

无筛选随机抽取，反映一般水平。

**HIVE / EXOSKELETONS_WEAK** (Monster, weak; 怪物 EXOSKELETON) — mutation / mut-v2 / 构筑 `b4f621ff4753`
- 牌组 28 张：ACCELERANT+1, ASCENDERS_BANE, BACKFLIP, DEADLY_POISON, DEFEND_SILENT×5, DEFLECT, DISCOVERY, ECHOING_SLASH+1, FINESSE+1, FLICK_FLACK, FOOTWORK+1 [SWIFT 2], MURDER+1, POUNCE, SALVO+1, SERPENT_FORM, SNAKEBITE+1, STRIKE_SILENT×3, STRIKE_SILENT+1×2, SUPPRESS, SURVIVOR [STEADY 1], TACTICIAN [STEADY 1]
- 遗物 9 件：RING_OF_THE_SNAKE, NEOWS_BONES, SCROLL_BOXES, POMANDER, HORN_CLEAT, ARCHAIC_TOOTH, REPTILE_TRINKET, THE_COURIER, TINY_MAILBOX
- 变异：large / both，改牌 3 改遗物 3，父代 `07ba3746bd42`
- 标签（4 个种子净掉血）：[4, 5, 0, 0] → 均值 **2.2**，组内 std 2.6，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 2.1 (-0.2, 死亡 0.00), repo_mlp 1.2 (-1.1, 死亡 0.00), rtdl_mlp 1.1 (-1.1, 死亡 0.00), rtdl_resnet 0.2 (-2.1, 死亡 0.00), set_transformer 0.6 (-1.6, 死亡 0.00), tabm 0.8 (-1.4, 死亡 0.00), ensemble 1.0 (-1.3, 死亡 0.00)

**UNDERDOCKS / PHANTASMAL_GARDENERS_ELITE** (Elite; 怪物 PHANTASMAL_GARDENER) — real / real-v3 / 构筑 `7c741c049fb5`
- 牌组 22 张：ASCENDERS_BANE, BACKFLIP, BUBBLE_BUBBLE, DEFEND_SILENT×4, FOOTWORK, NEUTRALIZE, NOXIOUS_FUMES, PIERCING_WAIL, POISONED_STAB×2, POUNCE, SNAKEBITE, STRIKE_SILENT×4, SUCKER_PUNCH, SUCKER_PUNCH+1, SURVIVOR
- 遗物 5 件：RING_OF_THE_SNAKE, SPARKLING_ROUGE, LANTERN, FESTIVE_POPPER, PERMAFROST
- 标签（4 个种子净掉血）：[7, 7, 6, 12] → 均值 **8.0**，组内 std 2.7，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 5.4 (-2.6, 死亡 0.00), repo_mlp 3.9 (-4.1, 死亡 0.00), rtdl_mlp 5.8 (-2.2, 死亡 0.00), rtdl_resnet 4.8 (-3.2, 死亡 0.00), set_transformer 3.7 (-4.3, 死亡 0.00), tabm 8.0 (-0.0, 死亡 0.00), ensemble 5.3 (-2.7, 死亡 0.00)

**HIVE / ENTOMANCER_ELITE** (Elite; 怪物 ENTOMANCER) — real / real-v3 / 构筑 `ff221936a692`
- 牌组 28 张：ACCELERANT, ACROBATICS, ADRENALINE+1, AFTERIMAGE+1, ASCENDERS_BANE, BLUR, DEFEND_SILENT×4, DEFEND_SILENT [SPIRAL 1], ESCAPE_PLAN, NEUTRALIZE+1, NOXIOUS_FUMES+1×2, PIERCING_WAIL, PINPOINT, PREPARED, RICOCHET, SIDESTEP, SKEWER+1, SNAKEBITE, STRIKE_SILENT×5, SURVIVOR
- 遗物 6 件：RING_OF_THE_SNAKE, ARCANE_SCROLL, FESTIVE_POPPER, BAG_OF_MARBLES, MERCURY_HOURGLASS, YUMMY_COOKIE
- 标签（4 个种子净掉血）：[13, 30, 11, 21] → 均值 **18.8**，组内 std 8.7，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 23.9 (+5.1, 死亡 0.00), repo_mlp 14.4 (-4.4, 死亡 0.00), rtdl_mlp 22.3 (+3.5, 死亡 0.00), rtdl_resnet 18.7 (-0.1, 死亡 0.00), set_transformer 19.7 (+1.0, 死亡 0.00), tabm 18.4 (-0.3, 死亡 0.00), ensemble 19.6 (+0.8, 死亡 0.00)

**HIVE / TUNNELER_WEAK** (Monster, weak; 怪物 TUNNELER) — real / real-v4 / 构筑 `20f7d4506a81`
- 牌组 25 张：AFTERIMAGE, ASCENDERS_BANE, BACKFLIP+1, CLOAK_AND_DAGGER+1, DAGGER_SPRAY, DEFEND_SILENT×5, DRAMATIC_ENTRANCE, ENVENOM, ESCAPE_PLAN, EXPOSE, FLECHETTES+1, LEADING_STRIKE, NEUTRALIZE+1, PIERCING_WAIL, SLICE, STRIKE_SILENT×5, SURVIVOR
- 遗物 8 件：RING_OF_THE_SNAKE, LOST_COFFER, PLANISPHERE, MERCURY_HOURGLASS, RED_MASK, VAJRA, HORN_CLEAT, PAELS_LEGION
- 标签（4 个种子净掉血）：[0, 0, 11, 0] → 均值 **2.8**，组内 std 5.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 2.4 (-0.4, 死亡 0.00), repo_mlp 2.3 (-0.5, 死亡 0.00), rtdl_mlp 2.6 (-0.1, 死亡 0.00), rtdl_resnet 1.2 (-1.6, 死亡 0.00), set_transformer 1.5 (-1.3, 死亡 0.00), tabm 1.6 (-1.2, 死亡 0.00), ensemble 1.9 (-0.8, 死亡 0.00)

**HIVE / HUNTER_KILLER_NORMAL** (Monster; 怪物 HUNTER_KILLER) — mutation / mut-v2 / 构筑 `c1926e3e3c4c`
- 牌组 30 张：AFTERIMAGE, ASCENDERS_BANE, BACKFLIP×2, BLADE_DANCE×2, DAGGER_THROW+1, DEFEND_SILENT×5, DODGE_AND_ROLL+1, ESCAPE_PLAN, FLECHETTES, HAND_TRICK, INFINITE_BLADES, MEMENTO_MORI [CORRUPTED 1], NEUTRALIZE+1, PINPOINT, PREPARED, PREPARED+1, SPOILS_MAP, STRIKE_SILENT×5, SURVIVOR, TACTICIAN
- 遗物 8 件：RING_OF_THE_SNAKE, LAVA_ROCK(HasTriggered=False), BRONZE_SCALES, BELLOWS, HAND_DRILL, HORN_CLEAT, PAELS_BLOOD, RAZOR_TOOTH
- 变异：small / relics，改牌 0 改遗物 1，父代 `eb57919140b1`
- 标签（4 个种子净掉血）：[7, 3, 6, 11] → 均值 **6.8**，组内 std 3.3，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 10.9 (+4.2, 死亡 0.00), repo_mlp 4.8 (-1.9, 死亡 0.00), rtdl_mlp 8.1 (+1.3, 死亡 0.00), rtdl_resnet 4.1 (-2.6, 死亡 0.00), set_transformer 4.3 (-2.5, 死亡 0.00), tabm 7.6 (+0.8, 死亡 0.00), ensemble 6.6 (-0.1, 死亡 0.00)

**HIVE / BOWLBUGS_WEAK** (Monster, weak; 怪物 BOWLBUG_EGG, BOWLBUG_NECTAR, BOWLBUG_ROCK) — real / real-v3 / 构筑 `051c0dab40de`
- 牌组 22 张：ASCENDERS_BANE, BLADE_OF_INK+1, BURST, DEFEND_SILENT×5, FLICK_FLACK, HAND_TRICK, NEUTRALIZE, NIGHTMARE, PINPOINT×2, PREPARED, SNAKEBITE+1, STRIKE_SILENT×5, SURVIVOR
- 遗物 6 件：RING_OF_THE_SNAKE, SHURIKEN, ODDLY_SMOOTH_STONE, JUZU_BRACELET, STRIKE_DUMMY, VERY_HOT_COCOA
- 标签（4 个种子净掉血）：[0, 0, 2, 0] → 均值 **0.5**，组内 std 1.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 5.3 (+4.8, 死亡 0.00), repo_mlp 3.2 (+2.7, 死亡 0.00), rtdl_mlp 2.0 (+1.5, 死亡 0.00), rtdl_resnet 1.7 (+1.2, 死亡 0.00), set_transformer 3.7 (+3.2, 死亡 0.00), tabm 2.2 (+1.7, 死亡 0.00), ensemble 3.0 (+2.5, 死亡 0.00)

**UNDERDOCKS / SEAPUNK_WEAK** (Monster, weak; 怪物 SEAPUNK) — real / real-v4 / 构筑 `0a175c661fa8`
- 牌组 15 张：ASCENDERS_BANE, DEFEND_SILENT×5, HIDDEN_DAGGERS, NEUTRALIZE, RICOCHET [GLAM 1], STRIKE_SILENT×5, SURVIVOR
- 遗物 3 件：RING_OF_THE_SNAKE, SILKEN_TRESS(IsUsed=False), FROZEN_EGG
- 标签（4 个种子净掉血）：[0, 0, 0, 3] → 均值 **0.8**，组内 std 1.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 2.5 (+1.7, 死亡 0.00), repo_mlp 2.3 (+1.6, 死亡 0.00), rtdl_mlp 0.9 (+0.2, 死亡 0.00), rtdl_resnet 2.9 (+2.1, 死亡 0.00), set_transformer 2.4 (+1.6, 死亡 0.00), tabm 1.3 (+0.6, 死亡 0.00), ensemble 2.0 (+1.3, 死亡 0.00)

**HIVE / EXOSKELETONS_WEAK** (Monster, weak; 怪物 EXOSKELETON) — real / real-v4 / 构筑 `2ef754d613e2`
- 牌组 23 张：ASCENDERS_BANE, ASSASSINATE, DEADLY_POISON×3, DEFEND_SILENT×4, DEFEND_SILENT [SPIRAL 1], ECHOING_SLASH, FASTEN+1, NEUTRALIZE, NOXIOUS_FUMES, PIERCING_WAIL+1, STRIKE_SILENT×5, SURVIVOR, ULTIMATE_DEFEND, WELL_LAID_PLANS
- 遗物 7 件：RING_OF_THE_SNAKE, BOOMING_CONCH, RIPPLE_BASIN, MUMMIFIED_HAND, CENTENNIAL_PUZZLE, AKABEKO, PAELS_TEARS
- 标签（4 个种子净掉血）：[1, 3, 1, 0] → 均值 **1.2**，组内 std 1.3，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 0.0 (-1.2, 死亡 0.00), repo_mlp 3.2 (+2.0, 死亡 0.00), rtdl_mlp 1.0 (-0.3, 死亡 0.00), rtdl_resnet 0.7 (-0.5, 死亡 0.00), set_transformer 0.3 (-0.9, 死亡 0.00), tabm 0.8 (-0.5, 死亡 0.00), ensemble 1.0 (-0.3, 死亡 0.00)

