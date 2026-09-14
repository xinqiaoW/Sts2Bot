# 预测样例与误差分析

快照 `/data2/pl/ImageTask/wxq/Projects/Sts2Bot/data/train-snapshots/20260913-121204`，测试集 138732 场 / 34690 对。主模型 **set_transformer**（pair MAE 4.54 HP，中位数 2.49，偏差 -0.47）。对比模型：lightgbm, repo_mlp, rtdl_mlp, rtdl_resnet, set_transformer, tabm, ensemble。误差 = 预测 − 同输入全部种子的均值，单位 HP。

## 误差分布（主模型，pair 级）

| 分位 | 25% | 50% | 75% | 90% | 95% | 99% |
|---|---|---|---|---|---|---|
| |误差| | 0.97 | 2.49 | 5.93 | 11.56 | 16.18 | 26.43 |

|误差| ≤ 2 HP 的 pair 占 43.5%，≤ 5 HP 占 70.3%，> 15 HP 占 5.9%。

注意“标签”本身是 4 个种子的均值，也带噪声：按组内 std/√n 估计，即使模型给出真实期望值，与 4 种子均值之间的 MAE 也约为 **2.48 HP**（正态近似 √(2/π)·std/√n 的平均）。因此主模型 pair MAE 4.54 中相当一部分来自标签噪声，而非模型误差。同理，“按标签均值分桶”中高标签桶的负偏差有一部分是选择效应（标签均值偶然偏高的 pair 被选进高桶），应以“按预测值分桶”判断校准。

## 校准：按预测值分桶

每桶给出 pair 数、平均预测、平均标签均值、偏差、MAE。理想情况下平均预测 ≈ 平均标签。

| 预测区间 | pairs | 平均预测 | 平均标签 | 偏差 | MAE |
|---|---|---|---|---|---|
| [0.0, 5.0) | 14471 | 2.09 | 2.57 | -0.47 | 1.65 |
| [5.0, 10.0) | 5892 | 7.28 | 7.79 | -0.52 | 3.97 |
| [10.0, 15.0) | 3745 | 12.35 | 13.12 | -0.77 | 5.41 |
| [15.0, 20.0) | 2607 | 17.38 | 17.79 | -0.41 | 6.40 |
| [20.0, 30.0) | 3143 | 24.53 | 25.27 | -0.74 | 8.29 |
| [30.0, 40.0) | 1896 | 34.77 | 35.13 | -0.36 | 10.26 |
| [40.0, 50.0) | 1267 | 44.66 | 44.65 | 0.01 | 11.02 |
| [50.0, 60.0) | 949 | 54.91 | 54.25 | 0.66 | 10.46 |
| [60.0, 70.01) | 720 | 64.40 | 64.53 | -0.14 | 5.54 |

## 校准：按标签均值分桶

看模型在高掉血/死亡输入上是否系统性低估（向均值回归）。

| 标签区间 | pairs | 平均标签 | 平均预测 | 偏差 | MAE | 组内 std |
|---|---|---|---|---|---|---|
| [0.0, 5.0) | 14660 | 1.77 | 3.03 | 1.27 | 2.00 | 2.21 |
| [5.0, 10.0) | 5754 | 7.12 | 7.88 | 0.76 | 3.66 | 5.93 |
| [10.0, 15.0) | 3474 | 12.22 | 12.52 | 0.31 | 4.80 | 7.96 |
| [15.0, 20.0) | 2402 | 17.25 | 17.04 | -0.21 | 5.85 | 9.30 |
| [20.0, 30.0) | 3166 | 24.42 | 22.84 | -1.58 | 7.33 | 11.19 |
| [30.0, 40.0) | 1883 | 34.40 | 30.92 | -3.47 | 9.05 | 13.96 |
| [40.0, 50.0) | 1236 | 44.52 | 38.52 | -6.00 | 10.39 | 15.61 |
| [50.0, 60.0) | 831 | 54.58 | 46.16 | -8.42 | 11.12 | 15.21 |
| [60.0, 70.01) | 1284 | 66.93 | 56.14 | -10.79 | 11.05 | 4.59 |

## 死亡概率校准（row 级）

| 预测死亡概率 | rows | 平均预测 | 实际死亡率 |
|---|---|---|---|
| [0.0, 0.02) | 123661 | 0.00 | 0.00 |
| [0.02, 0.05) | 2107 | 0.03 | 0.06 |
| [0.05, 0.1) | 3423 | 0.07 | 0.12 |
| [0.1, 0.2) | 3024 | 0.14 | 0.26 |
| [0.2, 0.4) | 2632 | 0.29 | 0.38 |
| [0.4, 0.6) | 1677 | 0.49 | 0.53 |
| [0.6, 0.8) | 1132 | 0.69 | 0.69 |
| [0.8, 1.01) | 1076 | 0.90 | 0.87 |

含死亡的 pair 2383 个（6.9%），其 pair MAE 10.94，偏差 -8.00；无死亡 pair MAE 4.07。全部种子死亡的 pair 505 个，平均预测 60.1 HP。

## 按怪物编组（主模型，pair 级）

按 MAE 从高到低；`弱` 为 weak 编组。

| 幕 | 编组 | 类型 | pairs | 平均标签 | 组内 std | 偏差 | MAE | 死亡场/总场 |
|---|---|---|---|---|---|---|---|---|
| GLORY | TEST_SUBJECT_BOSS | Boss | 412 | 48.62 | 13.90 | -2.61 | 12.41 | 646/1648 |
| GLORY | QUEEN_BOSS | Boss | 388 | 46.28 | 12.76 | -3.51 | 11.78 | 471/1542 |
| HIVE | THE_INSATIABLE_BOSS | Boss | 282 | 46.36 | 15.09 | 2.56 | 11.49 | 437/1128 |
| HIVE | KNOWLEDGE_DEMON_BOSS | Boss | 226 | 45.65 | 13.65 | -0.14 | 11.14 | 302/904 |
| GLORY | AEONGLASS_BOSS | Boss | 350 | 51.65 | 12.95 | -1.14 | 10.41 | 695/1400 |
| GLORY | KNIGHTS_ELITE | Elite | 583 | 23.29 | 13.11 | 1.27 | 10.30 | 143/2332 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | Boss | 181 | 40.60 | 9.11 | 0.25 | 9.73 | 216/724 |
| OVERGROWTH | THE_KIN_BOSS | Boss | 281 | 42.14 | 9.76 | -0.96 | 9.50 | 273/1124 |
| HIVE | KAISER_CRAB_BOSS | Boss | 232 | 45.60 | 10.34 | -4.03 | 9.45 | 205/928 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | Boss | 249 | 36.87 | 9.75 | -1.58 | 9.22 | 115/996 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | Boss | 145 | 39.75 | 8.72 | 0.84 | 9.13 | 87/580 |
| GLORY | MECHA_KNIGHT_ELITE | Elite | 632 | 22.65 | 12.11 | -1.64 | 9.09 | 76/2528 |
| GLORY | CONSTRUCT_MENAGERIE_NORMAL | Monster | 355 | 16.31 | 8.79 | -1.22 | 8.18 | 46/1420 |
| HIVE | DECIMILLIPEDE_ELITE | Elite | 783 | 26.92 | 10.63 | -0.07 | 8.11 | 190/3132 |
| OVERGROWTH | VANTOM_BOSS | Boss | 253 | 35.18 | 10.11 | 1.03 | 7.63 | 81/1011 |
| UNDERDOCKS | SOUL_FYSH_BOSS | Boss | 171 | 36.41 | 10.78 | -1.70 | 7.43 | 67/684 |
| HIVE | ENTOMANCER_ELITE | Elite | 759 | 21.07 | 10.13 | 0.82 | 7.35 | 176/3035 |
| HIVE | INFESTED_PRISMS_ELITE | Elite | 745 | 24.22 | 8.29 | -2.85 | 7.05 | 30/2979 |
| HIVE | SLUMBERING_BEETLE_NORMAL | Monster | 375 | 17.65 | 9.31 | -1.40 | 6.95 | 29/1500 |
| GLORY | SOUL_NEXUS_ELITE | Elite | 691 | 15.33 | 9.04 | -0.61 | 6.79 | 31/2763 |
| GLORY | AXEBOTS_NORMAL | Monster | 284 | 12.95 | 9.36 | -1.86 | 6.63 | 4/1136 |
| GLORY | THE_LOST_AND_FORGOTTEN_NORMAL | Monster | 444 | 8.83 | 7.49 | 3.08 | 6.48 | 13/1776 |
| OVERGROWTH | PHROG_PARASITE_ELITE | Elite | 864 | 22.38 | 9.13 | 0.26 | 6.04 | 365/3455 |
| OVERGROWTH | BYGONE_EFFIGY_ELITE | Elite | 859 | 21.59 | 7.69 | 0.83 | 5.85 | 83/3436 |
| UNDERDOCKS | PHANTASMAL_GARDENERS_ELITE | Elite | 583 | 26.58 | 7.75 | -0.54 | 5.82 | 208/2332 |
| UNDERDOCKS | CULTISTS_NORMAL | Monster | 209 | 18.12 | 8.75 | -1.05 | 5.66 | 32/836 |
| HIVE | OVICOPTER_NORMAL | Monster | 456 | 11.65 | 8.23 | -0.10 | 5.50 | 28/1824 |
| GLORY | SLIMED_BERSERKER_NORMAL | Monster | 303 | 8.00 | 6.80 | -0.81 | 5.44 | 9/1211 |
| OVERGROWTH | OVERGROWTH_CRAWLERS | Monster | 262 | 16.17 | 7.60 | -0.96 | 5.39 | 16/1048 |
| GLORY | FABRICATOR_NORMAL | Monster | 220 | 7.21 | 6.54 | -0.69 | 5.33 | 0/877 |
| GLORY | SCROLLS_OF_BITING_NORMAL | Monster | 278 | 12.98 | 9.62 | -1.15 | 5.17 | 15/1112 |
| GLORY | DEVOTED_SCULPTOR_WEAK | Monster弱 | 805 | 7.16 | 6.34 | 1.12 | 5.05 | 16/3220 |
| UNDERDOCKS | TERROR_EEL_ELITE | Elite | 633 | 24.82 | 6.93 | -1.44 | 5.03 | 113/2532 |
| HIVE | MYTES_NORMAL | Monster | 374 | 10.86 | 6.61 | -1.54 | 4.81 | 1/1496 |
| GLORY | OWL_MAGISTRATE_NORMAL | Monster | 237 | 9.61 | 6.70 | -1.13 | 4.75 | 1/948 |
| HIVE | THE_OBSCURA_NORMAL | Monster | 378 | 9.23 | 6.74 | 0.95 | 4.70 | 17/1512 |
| OVERGROWTH | BYRDONIS_ELITE | Elite | 848 | 20.82 | 6.36 | -0.99 | 4.69 | 32/3392 |
| HIVE | HUNTER_KILLER_NORMAL | Monster | 441 | 13.05 | 7.02 | -0.06 | 4.42 | 2/1763 |
| HIVE | CHOMPERS_NORMAL | Monster | 389 | 11.12 | 5.80 | -0.46 | 4.32 | 1/1555 |
| HIVE | BOWLBUGS_NORMAL | Monster | 294 | 8.33 | 6.44 | 0.74 | 4.23 | 0/1176 |
| GLORY | FROG_KNIGHT_NORMAL | Monster | 269 | 6.80 | 4.96 | -1.88 | 3.99 | 1/1076 |
| OVERGROWTH | SNAPPING_JAXFRUIT_NORMAL | Monster | 219 | 12.68 | 5.69 | -1.20 | 3.96 | 0/876 |
| GLORY | GLOBE_HEAD_NORMAL | Monster | 274 | 5.75 | 3.94 | 0.85 | 3.91 | 0/1096 |
| HIVE | SPINY_TOAD_NORMAL | Monster | 405 | 9.03 | 5.30 | -1.08 | 3.59 | 0/1620 |
| HIVE | LOUSE_PROGENITOR_NORMAL | Monster | 369 | 7.30 | 4.98 | 0.43 | 3.57 | 0/1476 |
| UNDERDOCKS | SKULKING_COLONY_ELITE | Elite | 540 | 17.00 | 5.47 | -0.94 | 3.50 | 0/2160 |
| OVERGROWTH | NIBBITS_NORMAL | Monster | 290 | 11.44 | 5.69 | -0.83 | 3.46 | 2/1160 |
| HIVE | TUNNELER_WEAK | Monster弱 | 814 | 6.46 | 5.21 | -0.91 | 3.34 | 3/3256 |
| UNDERDOCKS | SEAPUNK_NORMAL | Monster | 181 | 13.55 | 6.03 | -0.78 | 3.34 | 3/724 |
| OVERGROWTH | RUBY_RAIDERS_NORMAL | Monster | 295 | 11.92 | 5.84 | -1.03 | 3.32 | 0/1180 |
| UNDERDOCKS | TWO_TAILED_RATS_NORMAL | Monster | 210 | 8.63 | 4.06 | -0.58 | 2.81 | 0/840 |
| HIVE | EXOSKELETONS_NORMAL | Monster | 361 | 4.97 | 3.72 | 0.05 | 2.80 | 0/1444 |
| OVERGROWTH | FLYCONID_NORMAL | Monster | 219 | 11.30 | 4.92 | -0.68 | 2.73 | 0/876 |
| OVERGROWTH | SLIMES_NORMAL | Monster | 258 | 7.37 | 4.52 | 0.13 | 2.67 | 0/1032 |
| UNDERDOCKS | HAUNTED_SHIP_NORMAL | Monster | 206 | 8.88 | 4.75 | -0.35 | 2.51 | 0/824 |
| GLORY | SCROLLS_OF_BITING_WEAK | Monster弱 | 767 | 4.13 | 3.49 | -0.19 | 2.50 | 0/3065 |
| UNDERDOCKS | LIVING_FOG_NORMAL | Monster | 200 | 5.42 | 3.01 | 0.49 | 2.39 | 0/799 |
| OVERGROWTH | INKLETS_NORMAL | Monster | 300 | 6.80 | 3.56 | -0.76 | 2.37 | 0/1200 |
| GLORY | TURRET_OPERATOR_WEAK | Monster弱 | 884 | 3.94 | 3.53 | -0.55 | 2.32 | 0/3536 |
| UNDERDOCKS | CORPSE_SLUGS_NORMAL | Monster | 199 | 6.73 | 3.14 | 0.27 | 2.30 | 0/796 |
| UNDERDOCKS | GREMLIN_MERC_NORMAL | Monster | 207 | 7.93 | 4.01 | -0.42 | 2.25 | 0/828 |
| OVERGROWTH | MAWLER_NORMAL | Monster | 284 | 6.78 | 4.33 | -0.13 | 2.23 | 0/1136 |
| HIVE | THIEVING_HOPPER_WEAK | Monster弱 | 762 | 3.99 | 3.63 | -0.74 | 2.19 | 0/3048 |
| HIVE | BOWLBUGS_WEAK | Monster弱 | 751 | 4.06 | 3.78 | -0.34 | 2.16 | 0/3004 |
| OVERGROWTH | CUBEX_CONSTRUCT_NORMAL | Monster | 271 | 5.55 | 3.60 | -0.75 | 2.16 | 0/1084 |
| UNDERDOCKS | FOSSIL_STALKER_NORMAL | Monster | 212 | 6.56 | 4.19 | -0.43 | 2.06 | 0/848 |
| OVERGROWTH | FOGMOG_NORMAL | Monster | 286 | 5.11 | 3.47 | -0.39 | 2.06 | 0/1144 |
| UNDERDOCKS | PUNCH_CONSTRUCT_NORMAL | Monster | 203 | 7.22 | 3.51 | -0.31 | 2.00 | 0/812 |
| UNDERDOCKS | SEWER_CLAM_NORMAL | Monster | 220 | 4.31 | 3.43 | -0.30 | 2.00 | 0/880 |
| OVERGROWTH | VINE_SHAMBLER_NORMAL | Monster | 285 | 5.91 | 3.27 | -0.66 | 1.97 | 0/1139 |
| OVERGROWTH | SLITHERING_STRANGLER_NORMAL | Monster | 203 | 4.45 | 3.84 | -0.20 | 1.91 | 0/812 |
| UNDERDOCKS | CORPSE_SLUGS_WEAK | Monster弱 | 551 | 4.01 | 2.47 | -0.96 | 1.62 | 0/2204 |
| HIVE | EXOSKELETONS_WEAK | Monster弱 | 885 | 2.23 | 2.21 | -0.21 | 1.43 | 0/3539 |
| UNDERDOCKS | SEAPUNK_WEAK | Monster弱 | 570 | 2.14 | 2.46 | -0.86 | 1.23 | 0/2280 |
| UNDERDOCKS | TOADPOLES_WEAK | Monster弱 | 560 | 2.89 | 2.36 | -0.47 | 1.19 | 0/2239 |
| UNDERDOCKS | SLUDGE_SPINNER_WEAK | Monster弱 | 548 | 2.58 | 2.69 | -0.66 | 1.19 | 0/2192 |
| OVERGROWTH | SHRINKER_BEETLE_WEAK | Monster弱 | 833 | 1.91 | 2.10 | -0.46 | 1.05 | 0/3332 |
| OVERGROWTH | SLIMES_WEAK | Monster弱 | 802 | 1.73 | 2.06 | -0.19 | 1.04 | 0/3208 |
| OVERGROWTH | FUZZY_WURM_CRAWLER_WEAK | Monster弱 | 860 | 1.67 | 1.75 | -0.39 | 1.03 | 0/3440 |
| OVERGROWTH | NIBBITS_WEAK | Monster弱 | 883 | 1.57 | 2.10 | -0.28 | 0.92 | 0/3532 |

## 编组内区分能力：模型是否只在预测“这个怪难不难”

基线 = 对每个编组恒定预测其**训练集**标签均值（只看怪、不看构筑）。若模型对同一编组的不同构筑预测几乎不变，其预测 std 会远小于标签 std，编组内相关系数接近 0，编组内 R² 也接近 0（R² = 1 − 模型 MSE / 基线 MSE，>0 表示比基线好）。

整体：模型 pair MAE 4.54，编组均值基线 pair MAE 7.86；基线 pair R² 0.528，模型 pair R² 0.817。编组内相关系数中位数 0.77，编组内 R² 中位数 0.58；模型在 79/80 个编组上优于基线，在 2 个编组上几乎没有区分能力（R² < 0.1）。模型预测 std / 标签 std 的中位数 0.80（接近 0 表示对该编组几乎恒定预测）。

按编组内 R² 从低到高（最像“不分青红皂白”的排在前面）：

| 幕 | 编组 | 类型 | pairs | 标签 std | 预测 std | 相关 | 编组内 R² | MAE 模型 | MAE 基线 |
|---|---|---|---|---|---|---|---|---|---|
| GLORY | THE_LOST_AND_FORGOTTEN_NORMAL | Monster | 444 | 8.53 | 7.38 | 0.42 | -0.08 | 6.48 | 6.81 |
| UNDERDOCKS | SEAPUNK_WEAK | Monster弱 | 570 | 1.78 | 0.96 | 0.56 | 0.09 | 1.23 | 1.35 |
| GLORY | FABRICATOR_NORMAL | Monster | 220 | 7.77 | 6.02 | 0.46 | 0.12 | 5.33 | 6.11 |
| GLORY | GLOBE_HEAD_NORMAL | Monster | 274 | 6.50 | 5.85 | 0.55 | 0.17 | 3.91 | 5.21 |
| OVERGROWTH | SLIMES_WEAK | Monster弱 | 802 | 1.58 | 1.07 | 0.52 | 0.23 | 1.04 | 1.26 |
| GLORY | TEST_SUBJECT_BOSS | Boss | 412 | 18.09 | 13.98 | 0.55 | 0.24 | 12.41 | 15.45 |
| OVERGROWTH | NIBBITS_WEAK | Monster弱 | 883 | 1.38 | 0.85 | 0.54 | 0.25 | 0.92 | 1.11 |
| GLORY | SLIMED_BERSERKER_NORMAL | Monster | 303 | 9.48 | 5.00 | 0.50 | 0.25 | 5.44 | 7.20 |
| UNDERDOCKS | SLUDGE_SPINNER_WEAK | Monster弱 | 548 | 1.76 | 0.98 | 0.63 | 0.27 | 1.19 | 1.45 |
| GLORY | DEVOTED_SCULPTOR_WEAK | Monster弱 | 805 | 9.26 | 8.11 | 0.63 | 0.31 | 5.05 | 6.42 |
| OVERGROWTH | FUZZY_WURM_CRAWLER_WEAK | Monster弱 | 860 | 1.83 | 1.10 | 0.60 | 0.33 | 1.03 | 1.43 |
| HIVE | THIEVING_HOPPER_WEAK | Monster弱 | 762 | 3.69 | 2.34 | 0.62 | 0.36 | 2.19 | 2.87 |
| UNDERDOCKS | CORPSE_SLUGS_WEAK | Monster弱 | 551 | 2.50 | 1.55 | 0.68 | 0.36 | 1.62 | 2.06 |
| OVERGROWTH | SHRINKER_BEETLE_WEAK | Monster弱 | 833 | 1.78 | 1.04 | 0.65 | 0.36 | 1.05 | 1.40 |
| GLORY | QUEEN_BOSS | Boss | 388 | 18.55 | 13.73 | 0.64 | 0.37 | 11.78 | 15.98 |
| HIVE | THE_INSATIABLE_BOSS | Boss | 282 | 17.99 | 13.31 | 0.63 | 0.37 | 11.49 | 15.07 |
| GLORY | MECHA_KNIGHT_ELITE | Elite | 632 | 14.68 | 11.00 | 0.63 | 0.37 | 9.09 | 12.02 |
| HIVE | LOUSE_PROGENITOR_NORMAL | Monster | 369 | 5.90 | 4.89 | 0.63 | 0.38 | 3.57 | 4.89 |
| GLORY | AXEBOTS_NORMAL | Monster | 284 | 11.47 | 7.92 | 0.63 | 0.38 | 6.63 | 9.13 |
| GLORY | TURRET_OPERATOR_WEAK | Monster弱 | 884 | 4.54 | 3.25 | 0.66 | 0.42 | 2.32 | 3.61 |
| GLORY | AEONGLASS_BOSS | Boss | 350 | 18.11 | 13.98 | 0.67 | 0.43 | 10.41 | 15.30 |
| GLORY | FROG_KNIGHT_NORMAL | Monster | 269 | 8.61 | 4.54 | 0.72 | 0.43 | 3.99 | 5.73 |
| UNDERDOCKS | TOADPOLES_WEAK | Monster弱 | 560 | 2.08 | 1.34 | 0.70 | 0.44 | 1.19 | 1.64 |
| GLORY | KNIGHTS_ELITE | Elite | 583 | 17.31 | 12.31 | 0.66 | 0.44 | 10.30 | 14.48 |
| HIVE | TUNNELER_WEAK | Monster弱 | 814 | 6.41 | 4.16 | 0.68 | 0.44 | 3.34 | 4.73 |
| HIVE | KNOWLEDGE_DEMON_BOSS | Boss | 226 | 19.14 | 13.55 | 0.67 | 0.44 | 11.14 | 16.54 |
| HIVE | EXOSKELETONS_WEAK | Monster弱 | 885 | 2.94 | 2.41 | 0.68 | 0.44 | 1.43 | 2.03 |
| HIVE | BOWLBUGS_NORMAL | Monster | 294 | 7.84 | 7.69 | 0.73 | 0.47 | 4.23 | 5.88 |
| HIVE | BOWLBUGS_WEAK | Monster弱 | 751 | 4.37 | 3.23 | 0.70 | 0.49 | 2.16 | 3.09 |
| HIVE | EXOSKELETONS_NORMAL | Monster | 361 | 6.09 | 4.83 | 0.70 | 0.49 | 2.80 | 4.83 |
| HIVE | MYTES_NORMAL | Monster | 374 | 9.76 | 7.18 | 0.71 | 0.49 | 4.81 | 7.48 |
| GLORY | SOUL_NEXUS_ELITE | Elite | 691 | 12.72 | 9.27 | 0.71 | 0.50 | 6.79 | 9.92 |
| HIVE | CHOMPERS_NORMAL | Monster | 389 | 8.32 | 7.20 | 0.73 | 0.51 | 4.32 | 6.53 |
| UNDERDOCKS | LIVING_FOG_NORMAL | Monster | 200 | 4.69 | 4.36 | 0.77 | 0.55 | 2.39 | 3.53 |
| HIVE | OVICOPTER_NORMAL | Monster | 456 | 12.66 | 9.87 | 0.75 | 0.57 | 5.50 | 9.12 |
| HIVE | INFESTED_PRISMS_ELITE | Elite | 745 | 14.23 | 11.24 | 0.78 | 0.57 | 7.05 | 11.57 |
| HIVE | KAISER_CRAB_BOSS | Boss | 232 | 17.87 | 14.76 | 0.79 | 0.57 | 9.45 | 15.32 |
| HIVE | SLUMBERING_BEETLE_NORMAL | Monster | 375 | 14.29 | 10.88 | 0.74 | 0.57 | 6.95 | 11.23 |
| GLORY | OWL_MAGISTRATE_NORMAL | Monster | 237 | 10.83 | 7.54 | 0.77 | 0.58 | 4.75 | 8.02 |
| GLORY | CONSTRUCT_MENAGERIE_NORMAL | Monster | 355 | 16.93 | 13.38 | 0.76 | 0.58 | 8.18 | 12.98 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | Boss | 249 | 17.71 | 14.27 | 0.77 | 0.59 | 9.22 | 15.20 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | Boss | 145 | 18.71 | 17.17 | 0.78 | 0.59 | 9.13 | 15.99 |
| OVERGROWTH | THE_KIN_BOSS | Boss | 281 | 18.54 | 13.76 | 0.77 | 0.59 | 9.50 | 16.25 |
| UNDERDOCKS | SEWER_CLAM_NORMAL | Monster | 220 | 4.84 | 3.77 | 0.77 | 0.59 | 2.00 | 3.22 |
| GLORY | SCROLLS_OF_BITING_WEAK | Monster弱 | 767 | 6.14 | 4.68 | 0.78 | 0.61 | 2.50 | 4.40 |
| HIVE | THE_OBSCURA_NORMAL | Monster | 378 | 10.92 | 9.34 | 0.79 | 0.62 | 4.70 | 8.00 |
| HIVE | ENTOMANCER_ELITE | Elite | 759 | 16.67 | 13.89 | 0.79 | 0.63 | 7.35 | 12.85 |
| OVERGROWTH | INKLETS_NORMAL | Monster | 300 | 5.38 | 4.48 | 0.81 | 0.64 | 2.37 | 4.44 |
| HIVE | SPINY_TOAD_NORMAL | Monster | 405 | 7.85 | 6.02 | 0.80 | 0.64 | 3.59 | 5.86 |
| UNDERDOCKS | SOUL_FYSH_BOSS | Boss | 171 | 15.77 | 14.12 | 0.81 | 0.65 | 7.43 | 12.83 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | Boss | 181 | 22.47 | 19.65 | 0.81 | 0.65 | 9.73 | 19.78 |
| OVERGROWTH | VANTOM_BOSS | Boss | 253 | 16.82 | 13.73 | 0.81 | 0.65 | 7.63 | 14.15 |
| HIVE | DECIMILLIPEDE_ELITE | Elite | 783 | 17.92 | 15.65 | 0.81 | 0.66 | 8.11 | 14.70 |
| OVERGROWTH | SLIMES_NORMAL | Monster | 258 | 6.11 | 5.61 | 0.82 | 0.67 | 2.67 | 4.93 |
| OVERGROWTH | SNAPPING_JAXFRUIT_NORMAL | Monster | 219 | 8.88 | 6.44 | 0.84 | 0.68 | 3.96 | 7.46 |
| HIVE | HUNTER_KILLER_NORMAL | Monster | 441 | 10.48 | 8.37 | 0.82 | 0.68 | 4.42 | 8.01 |
| OVERGROWTH | VINE_SHAMBLER_NORMAL | Monster | 285 | 4.56 | 3.63 | 0.84 | 0.68 | 1.97 | 3.66 |
| OVERGROWTH | CUBEX_CONSTRUCT_NORMAL | Monster | 271 | 5.50 | 4.52 | 0.86 | 0.71 | 2.16 | 4.30 |
| UNDERDOCKS | HAUNTED_SHIP_NORMAL | Monster | 206 | 6.15 | 5.85 | 0.85 | 0.72 | 2.51 | 5.04 |
| UNDERDOCKS | PUNCH_CONSTRUCT_NORMAL | Monster | 203 | 4.73 | 3.98 | 0.85 | 0.73 | 2.00 | 4.08 |
| OVERGROWTH | NIBBITS_NORMAL | Monster | 290 | 9.00 | 7.51 | 0.86 | 0.74 | 3.46 | 7.37 |
| OVERGROWTH | MAWLER_NORMAL | Monster | 284 | 5.64 | 4.62 | 0.86 | 0.74 | 2.23 | 4.49 |
| GLORY | SCROLLS_OF_BITING_NORMAL | Monster | 278 | 13.22 | 10.39 | 0.85 | 0.74 | 5.17 | 10.40 |
| OVERGROWTH | OVERGROWTH_CRAWLERS | Monster | 262 | 15.59 | 12.74 | 0.87 | 0.75 | 5.39 | 12.77 |
| OVERGROWTH | SLITHERING_STRANGLER_NORMAL | Monster | 203 | 5.61 | 4.08 | 0.87 | 0.75 | 1.91 | 4.14 |
| UNDERDOCKS | GREMLIN_MERC_NORMAL | Monster | 207 | 6.00 | 5.32 | 0.87 | 0.76 | 2.25 | 4.78 |
| OVERGROWTH | FOGMOG_NORMAL | Monster | 286 | 6.11 | 5.13 | 0.87 | 0.77 | 2.06 | 4.89 |
| OVERGROWTH | BYGONE_EFFIGY_ELITE | Elite | 859 | 16.28 | 14.87 | 0.88 | 0.77 | 5.85 | 13.51 |
| UNDERDOCKS | FOSSIL_STALKER_NORMAL | Monster | 212 | 6.10 | 5.18 | 0.88 | 0.77 | 2.06 | 4.71 |
| UNDERDOCKS | CULTISTS_NORMAL | Monster | 209 | 17.33 | 14.10 | 0.90 | 0.80 | 5.66 | 13.79 |
| OVERGROWTH | RUBY_RAIDERS_NORMAL | Monster | 295 | 10.03 | 8.44 | 0.90 | 0.80 | 3.32 | 7.56 |
| UNDERDOCKS | SKULKING_COLONY_ELITE | Elite | 540 | 10.12 | 9.00 | 0.90 | 0.80 | 3.50 | 7.96 |
| OVERGROWTH | BYRDONIS_ELITE | Elite | 848 | 14.09 | 11.93 | 0.90 | 0.80 | 4.69 | 11.58 |
| OVERGROWTH | FLYCONID_NORMAL | Monster | 219 | 8.52 | 6.99 | 0.91 | 0.81 | 2.73 | 6.67 |
| UNDERDOCKS | TWO_TAILED_RATS_NORMAL | Monster | 210 | 9.47 | 7.44 | 0.91 | 0.81 | 2.81 | 7.34 |
| OVERGROWTH | PHROG_PARASITE_ELITE | Elite | 864 | 20.37 | 18.51 | 0.92 | 0.84 | 6.04 | 17.39 |
| UNDERDOCKS | CORPSE_SLUGS_NORMAL | Monster | 199 | 7.66 | 7.30 | 0.92 | 0.84 | 2.30 | 6.03 |
| UNDERDOCKS | SEAPUNK_NORMAL | Monster | 181 | 11.42 | 9.65 | 0.93 | 0.85 | 3.34 | 9.24 |
| UNDERDOCKS | PHANTASMAL_GARDENERS_ELITE | Elite | 583 | 20.42 | 18.64 | 0.92 | 0.85 | 5.82 | 16.91 |
| UNDERDOCKS | TERROR_EEL_ELITE | Elite | 633 | 17.92 | 16.49 | 0.93 | 0.86 | 5.03 | 13.89 |

各 Boss 编组内的预测分布（分位数），对照标签均值分布：

| 幕 | Boss | pairs | 标签 10%/50%/90% | 预测 10%/50%/90% |
|---|---|---|---|---|
| GLORY | AEONGLASS_BOSS | 350 | 26 / 57 / 70 | 30 / 54 / 66 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | 249 | 15 / 33 / 65 | 19 / 33 / 57 |
| HIVE | KAISER_CRAB_BOSS | 232 | 22 / 47 / 69 | 20 / 44 / 61 |
| HIVE | KNOWLEDGE_DEMON_BOSS | 226 | 18 / 50 / 70 | 27 / 47 / 63 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | 181 | 10 / 40 / 70 | 14 / 39 / 67 |
| GLORY | QUEEN_BOSS | 388 | 19 / 48 / 70 | 23 / 44 / 60 |
| UNDERDOCKS | SOUL_FYSH_BOSS | 171 | 17 / 36 / 58 | 16 / 34 / 55 |
| GLORY | TEST_SUBJECT_BOSS | 412 | 21 / 51 / 70 | 27 / 46 / 64 |
| HIVE | THE_INSATIABLE_BOSS | 282 | 22 / 47 / 70 | 29 / 52 / 65 |
| OVERGROWTH | THE_KIN_BOSS | 281 | 19 / 40 / 70 | 23 / 41 / 60 |
| OVERGROWTH | VANTOM_BOSS | 253 | 14 / 34 / 58 | 17 / 37 / 55 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | 145 | 16 / 37 / 66 | 17 / 41 / 63 |

## 按房间类型、幕、来源类型

### 房间类型

| 房间类型 | pairs | 平均标签 | 偏差 | MAE | MAE lightgbm | MAE repo_mlp | MAE rtdl_mlp | MAE rtdl_resnet | MAE tabm | MAE ensemble |
|---|---|---|---|---|---|---|---|---|---|---|
| Boss | 3170 | 43.94 | -1.14 | 10.26 | 12.12 | 11.31 | 11.55 | 10.70 | 10.59 | 10.07 |
| Elite | 8520 | 22.24 | -0.46 | 6.61 | 7.93 | 7.34 | 7.34 | 6.85 | 6.98 | 6.44 |
| Monster | 11725 | 9.58 | -0.39 | 4.02 | 4.85 | 4.21 | 4.35 | 4.02 | 4.26 | 3.91 |
| Monster(weak) | 11275 | 3.37 | -0.38 | 1.92 | 2.32 | 1.98 | 1.98 | 1.93 | 2.02 | 1.84 |

### 幕

| 幕 | pairs | 平均标签 | 偏差 | MAE | MAE lightgbm | MAE repo_mlp | MAE rtdl_mlp | MAE rtdl_resnet | MAE tabm | MAE ensemble |
|---|---|---|---|---|---|---|---|---|---|---|
| GLORY | 8176 | 16.35 | -0.51 | 6.48 | 7.53 | 7.06 | 7.14 | 6.57 | 6.77 | 6.37 |
| HIVE | 10081 | 14.14 | -0.45 | 4.94 | 5.77 | 5.25 | 5.33 | 5.02 | 5.24 | 4.75 |
| OVERGROWTH | 9904 | 12.01 | -0.34 | 3.39 | 4.28 | 3.71 | 3.76 | 3.55 | 3.51 | 3.31 |
| UNDERDOCKS | 6529 | 12.86 | -0.64 | 3.26 | 4.09 | 3.48 | 3.55 | 3.33 | 3.50 | 3.17 |

### 来源类型

| 来源类型 | pairs | 平均标签 | 偏差 | MAE | MAE lightgbm | MAE repo_mlp | MAE rtdl_mlp | MAE rtdl_resnet | MAE tabm | MAE ensemble |
|---|---|---|---|---|---|---|---|---|---|---|
| mutation | 6807 | 14.72 | -0.37 | 5.70 | 6.77 | 6.31 | 6.33 | 5.97 | 6.11 | 5.67 |
| real | 27883 | 13.59 | -0.49 | 4.26 | 5.12 | 4.56 | 4.64 | 4.32 | 4.46 | 4.12 |

### 牌组张数

| 牌组张数 | pairs | 平均标签 | 偏差 | MAE |
|---|---|---|---|---|
| [0, 12) | 8 | 2.81 | 0.90 | 1.79 |
| [12, 16) | 3264 | 6.55 | -0.62 | 1.82 |
| [16, 20) | 8773 | 12.48 | -0.53 | 3.33 |
| [20, 25) | 9351 | 13.48 | -0.39 | 4.48 |
| [25, 30) | 6974 | 14.83 | -0.50 | 5.44 |
| [30, 46) | 6320 | 18.79 | -0.40 | 6.74 |

### 遗物件数

| 遗物件数 | pairs | 平均标签 | 偏差 | MAE |
|---|---|---|---|---|
| [0, 3) | 6969 | 9.88 | -0.56 | 2.42 |
| [3, 5) | 5789 | 13.37 | -0.58 | 3.72 |
| [5, 8) | 8227 | 13.41 | -0.28 | 4.40 |
| [8, 12) | 6494 | 14.87 | -0.21 | 5.57 |
| [12, 40) | 7211 | 17.47 | -0.75 | 6.49 |

## 模型分歧

各模型预测极差的中位数 5.49 HP，90% 分位 16.59。分歧最大的 pair 与其真值：

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — real / real-v3 / 构筑 `d4bb77268777`
- 牌组 45 张：ACCELERANT+1×2, ANTICIPATE [SWIFT 1], ASCENDERS_BANE, ASSASSINATE+1, BACKFLIP×2, BLADE_DANCE+1, BOUNCING_FLASK×2, BUBBLE_BUBBLE, CLUMSY, DEADLY_POISON, DEADLY_POISON [SWIFT 1], DEFEND_SILENT×2, DEFEND_SILENT [ADROIT 3]×3, DEFLECT, ENVENOM+1, ESCAPE_PLAN, EXPOSE, FOOTWORK, LEADING_STRIKE+1, MIRAGE+1, NEUTRALIZE, PANACHE+1 [SWIFT 2], PIERCING_WAIL, POISONED_STAB, POISONED_STAB+1, PREPARED+1, PRODUCTION, PRODUCTION+1, REFLEX, SPEEDSTER, STRIKE_SILENT+1×3, SURVIVOR, TACTICIAN+1, THINKING_AHEAD, UNTOUCHABLE, UNTOUCHABLE+1, WHISTLE
- 遗物 30 件：RING_OF_THE_SNAKE, LOST_COFFER, DREAM_CATCHER, VAJRA, BRONZE_SCALES, KIFUDA, DINGY_RUG, NUNCHAKU(AttacksPlayed=5), AMETHYST_AUBERGINE, HAPPY_FLOWER(TurnsSeen=1), GLASS_EYE, ODDLY_SMOOTH_STONE, LANTERN, RINGING_TRIANGLE, PANTOGRAPH, STURDY_CLAMP, WONGOS_MYSTERY_TICKET(CombatsFinished=3,GaveRelic=False), PERMAFROST, WHITE_STAR, SLING_OF_COURAGE, PLANISPHERE, TANXS_WHISTLE, POTION_BELT, REGAL_PILLOW, WING_CHARM, CENTENNIAL_PUZZLE, WHETSTONE, RED_MASK, BAG_OF_PREPARATION, VENERABLE_TEA_SET(GainEnergyInNextCombat=True)
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 64.2 (-5.8, 死亡 0.49), repo_mlp 41.3 (-28.7, 死亡 0.34), rtdl_mlp 18.6 (-51.4, 死亡 0.00), rtdl_resnet 10.2 (-59.8, 死亡 0.00), set_transformer 54.3 (-15.7, 死亡 0.36), tabm 34.1 (-35.9, 死亡 0.16), ensemble 37.1 (-32.9, 死亡 0.23)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — real / real-v3 / 构筑 `74be9cdc79ca`
- 牌组 43 张：ACCELERANT+1×2, ASCENDERS_BANE, ASSASSINATE+1, BACKFLIP×2, BOUNCING_FLASK×2, BUBBLE_BUBBLE, CLUMSY, DEADLY_POISON, DEADLY_POISON [SWIFT 1], DEFEND_SILENT×2, DEFEND_SILENT [ADROIT 3]×3, DEFLECT, ENVENOM+1, ESCAPE_PLAN, EXPOSE, FOOTWORK, LEADING_STRIKE+1, MIRAGE+1, NEUTRALIZE, PANACHE+1 [SWIFT 2], PIERCING_WAIL, POISONED_STAB, POISONED_STAB+1, PREPARED+1, PRODUCTION, PRODUCTION+1, REFLEX, SPEEDSTER, STRIKE_SILENT+1×3, SURVIVOR, TACTICIAN+1, THINKING_AHEAD, UNTOUCHABLE, UNTOUCHABLE+1, WHISTLE
- 遗物 30 件：RING_OF_THE_SNAKE, LOST_COFFER, DREAM_CATCHER, VAJRA, BRONZE_SCALES, KIFUDA, DINGY_RUG, NUNCHAKU(AttacksPlayed=0), AMETHYST_AUBERGINE, HAPPY_FLOWER(TurnsSeen=2), GLASS_EYE, ODDLY_SMOOTH_STONE, LANTERN, RINGING_TRIANGLE, PANTOGRAPH, STURDY_CLAMP, WONGOS_MYSTERY_TICKET(CombatsFinished=5,GaveRelic=True), PERMAFROST, WHITE_STAR, SLING_OF_COURAGE, PLANISPHERE, TANXS_WHISTLE, POTION_BELT, REGAL_PILLOW, WING_CHARM, CENTENNIAL_PUZZLE, WHETSTONE, RED_MASK, BAG_OF_PREPARATION, VENERABLE_TEA_SET(GainEnergyInNextCombat=True)
- 标签（4 个种子净掉血）：[70, 70, 70, 39] → 均值 **62.2**，组内 std 15.5，死亡 3/4
- 预测（误差，死亡概率）：lightgbm 64.9 (+2.6, 死亡 0.50), repo_mlp 40.3 (-22.0, 死亡 0.29), rtdl_mlp 18.1 (-44.2, 死亡 0.00), rtdl_resnet 12.3 (-50.0, 死亡 0.00), set_transformer 47.0 (-15.2, 死亡 0.21), tabm 36.0 (-26.3, 死亡 0.19), ensemble 36.4 (-25.8, 死亡 0.20)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — mutation / mut-v2 / 构筑 `2ed6d00eaad5`
- 牌组 45 张：ACCELERANT+1, ASCENDERS_BANE, ASSASSINATE+1, AUTOMATION+1, BACKFLIP×2, BOUNCING_FLASK×3, BUBBLE_BUBBLE, CLUMSY, DEADLY_POISON, DEADLY_POISON [SWIFT 1], DEFEND_SILENT×2, DEFEND_SILENT [ADROIT 3]×3, DEFLECT, DISCOVERY+1, ENVENOM+1, ESCAPE_PLAN, EXPOSE, FOOTWORK, HIDDEN_DAGGERS, LEADING_STRIKE+1, MIRAGE+1, NEUTRALIZE, PANACHE+1 [SWIFT 2], PIERCING_WAIL, POISONED_STAB, POISONED_STAB+1, PRECISE_CUT+1, PREPARED+1, PRODUCTION+1, REFLEX, STRIKE_SILENT+1×3, SURVIVOR, TACTICIAN+1, THINKING_AHEAD, UNTOUCHABLE, UNTOUCHABLE+1, WHISTLE
- 遗物 30 件：RING_OF_THE_SNAKE, LOST_COFFER, DREAM_CATCHER, VAJRA, BRONZE_SCALES, KIFUDA, DINGY_RUG, NUNCHAKU(AttacksPlayed=0), AMETHYST_AUBERGINE, HAPPY_FLOWER(TurnsSeen=2), GLASS_EYE, ODDLY_SMOOTH_STONE, LANTERN, RINGING_TRIANGLE, PANTOGRAPH, STURDY_CLAMP, WONGOS_MYSTERY_TICKET(CombatsFinished=5,GaveRelic=True), PERMAFROST, WHITE_STAR, SLING_OF_COURAGE, PLANISPHERE, TANXS_WHISTLE, POTION_BELT, REGAL_PILLOW, WING_CHARM, CENTENNIAL_PUZZLE, WHETSTONE, RED_MASK, BAG_OF_PREPARATION, VENERABLE_TEA_SET(GainEnergyInNextCombat=True)
- 变异：large / cards，改牌 5 改遗物 0，父代 `74be9cdc79ca`
- 标签（4 个种子净掉血）：[70, 44, 70, 42] → 均值 **56.5**，组内 std 15.6，死亡 2/4
- 预测（误差，死亡概率）：lightgbm 64.4 (+7.9, 死亡 0.47), repo_mlp 40.8 (-15.7, 死亡 0.30), rtdl_mlp 18.5 (-38.0, 死亡 0.00), rtdl_resnet 13.9 (-42.6, 死亡 0.01), set_transformer 51.8 (-4.7, 死亡 0.28), tabm 36.1 (-20.4, 死亡 0.16), ensemble 37.6 (-18.9, 死亡 0.20)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — real / real-v4 / 构筑 `79978f8e09ea`
- 牌组 31 张：AFTERIMAGE, ASCENDERS_BANE, CLOAK_AND_DAGGER, CLOAK_AND_DAGGER+1, CLUMSY, DAGGER_THROW, DAGGER_THROW [SWIFT 2], DEFEND_SILENT×4, DEFLECT, FLICK_FLACK×3, NEUTRALIZE [SWIFT 2], PREPARED, PREPARED+1×2, PREPARED+1 [IMBUED 1], RICOCHET, RICOCHET [SWIFT 2]×2, SHADOW_STEP+1, SPEEDSTER+1, STRIKE_SILENT×3, SURVIVOR, TACTICIAN+1, ULTIMATE_STRIKE
- 遗物 19 件：RING_OF_THE_SNAKE, BAG_OF_MARBLES, VAJRA, CENTENNIAL_PUZZLE, BAG_OF_PREPARATION, ELECTRIC_SHRYMP, DAUGHTER_OF_THE_WIND, NUNCHAKU(AttacksPlayed=5), TUNING_FORK(SkillsPlayed=8), MERCURY_HOURGLASS, PARRYING_SHIELD, BEAUTIFUL_BRACELET, HISTORY_COURSE, VENERABLE_TEA_SET(GainEnergyInNextCombat=True), ODDLY_SMOOTH_STONE, SPARKLING_ROUGE, PENDULUM(TurnsSeen=0), POTION_BELT, LANTERN
- 标签（4 个种子净掉血）：[70, 70, 70, 53] → 均值 **65.8**，组内 std 8.5，死亡 3/4
- 预测（误差，死亡概率）：lightgbm 57.2 (-8.6, 死亡 0.63), repo_mlp 52.7 (-13.1, 死亡 0.37), rtdl_mlp 55.9 (-9.9, 死亡 0.57), rtdl_resnet 46.0 (-19.7, 死亡 0.32), set_transformer 15.0 (-50.8, 死亡 0.01), tabm 61.8 (-4.0, 死亡 0.74), ensemble 48.1 (-17.7, 死亡 0.44)

## 最严重高估（预测 ≫ 标签）

模型认为会掉很多血，实际老师打得轻松。

**GLORY / QUEEN_BOSS** (Boss; 怪物 QUEEN, TORCH_HEAD_AMALGAM) — real / real-v3 / 构筑 `eee31be9eecb`
- 牌组 32 张：ABRASIVE, ACCELERANT, ACROBATICS×2, ACROBATICS+1×2, ADRENALINE, ASCENDERS_BANE, CORROSIVE_WAVE+1, DEFEND_SILENT×5, DEFLECT, EXPERTISE, EXPOSE, FLECHETTES, FOOTWORK, LEADING_STRIKE+1, NEUTRALIZE, PREPARED+1×2, REFLEX+1, RICOCHET×2, RICOCHET [VIGOROUS 8], SLICE [SHARP 2], SPEEDSTER+1, SURVIVOR, TACTICIAN+1, UNTOUCHABLE
- 遗物 14 件：RING_OF_THE_SNAKE, SILVER_CRUCIBLE(TimesUsed=2,TreasureRoomsEntered=2), TUNING_FORK(SkillsPlayed=1), GORGET, VERY_HOT_COCOA, ANCHOR, BLOOD_VIAL, STURDY_CLAMP, THROWING_AXE, ETERNAL_FEATHER, ORRERY, BRONZE_SCALES, POTION_BELT, POCKETWATCH
- 标签（4 个种子净掉血）：[0, 10, 0, 1] → 均值 **2.8**，组内 std 4.9，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 48.6 (+45.8, 死亡 0.41), repo_mlp 50.5 (+47.8, 死亡 0.20), rtdl_mlp 54.1 (+51.3, 死亡 0.55), rtdl_resnet 41.9 (+39.2, 死亡 0.27), set_transformer 60.5 (+57.8, 死亡 0.56), tabm 56.6 (+53.8, 死亡 0.52), ensemble 52.0 (+49.3, 死亡 0.42)

**UNDERDOCKS / WATERFALL_GIANT_BOSS** (Boss; 怪物 WATERFALL_GIANT) — real / real-v3 / 构筑 `8c07372930eb`
- 牌组 17 张：ASCENDERS_BANE, DEFEND_SILENT×5, ESCAPE_PLAN, EXPOSE, INFINITE_BLADES+1×2, NEUTRALIZE+1, PURITY, STRIKE_SILENT×4, SURVIVOR
- 遗物 5 件：RING_OF_THE_SNAKE, GOLDEN_PEARL, DINGY_RUG, KUNAI, PEN_NIB(AttacksPlayed=1)
- 标签（4 个种子净掉血）：[15, 4, 4, 8] → 均值 **7.8**，组内 std 5.2，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 58.1 (+50.3, 死亡 0.12), repo_mlp 52.0 (+44.2, 死亡 0.35), rtdl_mlp 48.6 (+40.9, 死亡 0.23), rtdl_resnet 39.5 (+31.7, 死亡 0.10), set_transformer 61.3 (+53.6, 死亡 0.41), tabm 35.0 (+27.3, 死亡 0.02), ensemble 49.1 (+41.3, 死亡 0.20)

**OVERGROWTH / BYRDONIS_ELITE** (Elite; 怪物 BYRDONIS) — real / real-v3 / 构筑 `dbf10b62ab94`
- 牌组 17 张：ASCENDERS_BANE, DEFEND_SILENT×5, DODGE_AND_ROLL [NIMBLE 2], GRAND_FINALE, INJURY, NEUTRALIZE, PREPARED, STRIKE_SILENT×3, SURVIVOR, THE_HUNT, UNTOUCHABLE
- 遗物 2 件：RING_OF_THE_SNAKE, HEFTY_TABLET
- 标签（4 个种子净掉血）：[5, 23, 4, 10] → 均值 **10.5**，组内 std 8.7，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 44.3 (+33.8, 死亡 0.12), repo_mlp 70.0 (+59.5, 死亡 0.86), rtdl_mlp 63.9 (+53.4, 死亡 0.56), rtdl_resnet 60.6 (+50.1, 死亡 0.53), set_transformer 59.6 (+49.1, 死亡 0.27), tabm 55.5 (+45.0, 死亡 0.26), ensemble 59.0 (+48.5, 死亡 0.43)

**GLORY / TEST_SUBJECT_BOSS** (Boss; 怪物 TEST_SUBJECT) — real / real-v4 / 构筑 `2e564b86683c`
- 牌组 28 张：ACCURACY, ASCENDERS_BANE, BACKFLIP, BULLET_TIME+1, DEBT, DEFEND_SILENT×5, DEFLECT+1, ESCAPE_PLAN, FLECHETTES+1 [SHARP 2], FOOTWORK+1×3, GREED, HAND_TRICK+1, HIDDEN_DAGGERS+1, LEG_SWEEP+1, NEUTRALIZE+1, PIERCING_WAIL+1, PREDATOR, PREPARED+1, STRIKE_SILENT×2, SURVIVOR, TRACKING+1
- 遗物 18 件：RING_OF_THE_SNAKE, CURSED_PEARL, ANCHOR, STRIKE_DUMMY, HAPPY_FLOWER(TurnsSeen=0), NUNCHAKU(AttacksPlayed=8), PENDULUM(TurnsSeen=1), BAG_OF_PREPARATION, RUNIC_PYRAMID, PERMAFROST, WAR_PAINT, JOSS_PAPER(CardsExhausted=1), PEN_NIB(AttacksPlayed=0), MUSIC_BOX, LANTERN, VAMBRACE, REGAL_PILLOW, FORGOTTEN_SOUL
- 标签（4 个种子净掉血）：[10, 0, 0, 12] → 均值 **5.5**，组内 std 6.4，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 47.3 (+41.8, 死亡 0.65), repo_mlp 67.5 (+62.0, 死亡 0.53), rtdl_mlp 48.0 (+42.5, 死亡 0.49), rtdl_resnet 50.4 (+44.9, 死亡 0.45), set_transformer 54.3 (+48.8, 死亡 0.47), tabm 56.1 (+50.6, 死亡 0.55), ensemble 53.9 (+48.4, 死亡 0.52)

**HIVE / KNOWLEDGE_DEMON_BOSS** (Boss; 怪物 KNOWLEDGE_DEMON) — real / real-v4 / 构筑 `29750fc3ab17`
- 牌组 26 张：AFTERIMAGE+1, ASCENDERS_BANE, BACKFLIP, BLADE_OF_INK+1, CALCULATED_GAMBLE, DEFEND_SILENT×4, DEFEND_SILENT [SPIRAL 1], EXPOSE×2, INFINITE_BLADES+1, LEADING_STRIKE, NEUTRALIZE+1 [SHARP 2], PHANTOM_BLADES, POUNCE, SNAKEBITE+1, SQUASH, STRIKE_SILENT [TEZCATARAS_EMBER 1]×3, STRIKE_SILENT+1 [TEZCATARAS_EMBER 1]×2, SURVIVOR, TOOLS_OF_THE_TRADE+1
- 遗物 9 件：RING_OF_THE_SNAKE, MEAL_TICKET, CAPTAINS_WHEEL, LUCKY_FYSH, NUTRITIOUS_SOUP, ORNAMENTAL_FAN, LOST_WISP, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), WHETSTONE
- 标签（4 个种子净掉血）：[20, 5, 1, 4] → 均值 **7.5**，组内 std 8.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 48.1 (+40.6, 死亡 0.20), repo_mlp 43.9 (+36.4, 死亡 0.14), rtdl_mlp 46.7 (+39.2, 死亡 0.33), rtdl_resnet 47.4 (+39.9, 死亡 0.33), set_transformer 52.5 (+45.0, 死亡 0.27), tabm 47.6 (+40.1, 死亡 0.35), ensemble 47.7 (+40.2, 死亡 0.27)

**UNDERDOCKS / LAGAVULIN_MATRIARCH_BOSS** (Boss; 怪物 LAGAVULIN_MATRIARCH) — real / real-v3 / 构筑 `861e2e208c16`
- 牌组 20 张：ASCENDERS_BANE, BLADE_DANCE, CLOAK_AND_DAGGER, DEFEND_SILENT×5, EXPOSE, EXPOSE+1, FOOTWORK, LEADING_STRIKE, NEUTRALIZE, PHANTOM_BLADES+1, PIERCING_WAIL, STRIKE_SILENT×4, SURVIVOR
- 遗物 6 件：RING_OF_THE_SNAKE, GOLDEN_PEARL, MINIATURE_TENT, AMETHYST_AUBERGINE, LETTER_OPENER, BRONZE_SCALES
- 标签（4 个种子净掉血）：[26, 19, 17, 28] → 均值 **22.5**，组内 std 5.3，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 55.9 (+33.4, 死亡 0.52), repo_mlp 58.3 (+35.8, 死亡 0.56), rtdl_mlp 42.3 (+19.8, 死亡 0.06), rtdl_resnet 66.3 (+43.8, 死亡 0.81), set_transformer 65.8 (+43.3, 死亡 0.83), tabm 52.0 (+29.5, 死亡 0.36), ensemble 56.8 (+34.3, 死亡 0.53)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — real / real-v3 / 构筑 `3d0c9c049dd6`
- 牌组 44 张：ACCELERANT+1, ACCURACY+1, ACROBATICS, ADRENALINE+1×3, ASCENDERS_BANE, BACKFLIP, BACKFLIP+1, BLADE_DANCE×2, BOUNCING_FLASK+1, CALCULATED_GAMBLE+1, CLOAK_AND_DAGGER, CLOAK_AND_DAGGER+1, CORROSIVE_WAVE, DAGGER_THROW, DECAY, DEFEND_SILENT×5, DEFLECT, EXPERTISE+1, HIDDEN_DAGGERS+1, LEADING_STRIKE, LEADING_STRIKE+1, LEG_SWEEP+1, NEUTRALIZE+1, NOXIOUS_FUMES+1, PANACHE+1, PIERCING_WAIL, POUNCE, PREPARED×2, SQUASH, STRIKE_SILENT×4, SURVIVOR [NIMBLE 2], TRACKING+1, UNTOUCHABLE
- 遗物 17 件：RING_OF_THE_SNAKE, GOLDEN_PEARL, STRIKE_DUMMY, POTION_BELT, ORNAMENTAL_FAN, VERY_HOT_COCOA, LOST_WISP, MOLTEN_EGG, THE_COURIER, DOLLYS_MIRROR, SNECKO_SKULL, IRON_CLUB(CardsPlayed=1), FESTIVE_POPPER, ODDLY_SMOOTH_STONE, TUNING_FORK(SkillsPlayed=1), CAPTAINS_WHEEL, PARRYING_SHIELD
- 标签（4 个种子净掉血）：[4, 3, 19, 36] → 均值 **15.5**，组内 std 15.5，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 38.7 (+23.2, 死亡 0.34), repo_mlp 44.9 (+29.4, 死亡 0.25), rtdl_mlp 44.5 (+29.0, 死亡 0.54), rtdl_resnet 39.5 (+24.0, 死亡 0.45), set_transformer 57.5 (+42.0, 死亡 0.47), tabm 26.3 (+10.8, 死亡 0.10), ensemble 41.9 (+26.4, 死亡 0.36)

**OVERGROWTH / VANTOM_BOSS** (Boss; 怪物 VANTOM) — real / real-v4 / 构筑 `d2380c54cb20`
- 牌组 23 张：ABUNDANCE, ASCENDERS_BANE, DAGGER_SPRAY, DAGGER_THROW, DEFEND_SILENT×5, DODGE_AND_ROLL, ESCAPE_PLAN, HIDDEN_DAGGERS, INFINITE_BLADES+1, NEUTRALIZE, RICOCHET×2, STRIKE_SILENT×5, SURVIVOR, UNTOUCHABLE
- 遗物 5 件：RING_OF_THE_SNAKE, DOWSING_ROD, MEAL_TICKET, CAPTAINS_WHEEL, LANTERN
- 标签（4 个种子净掉血）：[12, 1, 1, 7] → 均值 **5.2**，组内 std 5.3，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 47.6 (+42.4, 死亡 0.05), repo_mlp 34.0 (+28.7, 死亡 0.01), rtdl_mlp 43.7 (+38.5, 死亡 0.05), rtdl_resnet 39.4 (+34.1, 死亡 0.01), set_transformer 47.1 (+41.8, 死亡 0.08), tabm 31.6 (+26.4, 死亡 0.01), ensemble 40.6 (+35.3, 死亡 0.04)

## 最严重低估（预测 ≪ 标签）

模型认为安全，实际老师掉血多或死亡。

**GLORY / THE_LOST_AND_FORGOTTEN_NORMAL** (Monster; 怪物 THE_LOST, THE_FORGOTTEN) — real / real-v3 / 构筑 `b716d1505a8f`
- 牌组 31 张：ACROBATICS, ADRENALINE [SOULS_POWER 1], AFTERIMAGE+1, ASCENDERS_BANE, ASSASSINATE+1, CLOAK_AND_DAGGER×2, DECAY, DEFEND_SILENT×5, DODGE_AND_ROLL, EXPOSE, FAN_OF_KNIVES, FOOTWORK+1, HIDDEN_DAGGERS, INFINITE_BLADES+1, KNIFE_TRAP, LEG_SWEEP, STRIKE_SILENT×4, SUPPRESS+1, SURVIVOR, TORIC_TOUGHNESS, UNTOUCHABLE×2, UP_MY_SLEEVE
- 遗物 12 件：RING_OF_THE_SNAKE, HEFTY_TABLET, PLANISPHERE, PERMAFROST, JOSS_PAPER(CardsExhausted=2), ARCHAIC_TOOTH, GORGET, ODDLY_SMOOTH_STONE, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), BEATING_REMNANT, SNECKO_SKULL, IRON_CLUB(CardsPlayed=3)
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 12.6 (-57.4, 死亡 0.00), repo_mlp 9.7 (-60.3, 死亡 0.00), rtdl_mlp 7.3 (-62.7, 死亡 0.00), rtdl_resnet 15.1 (-54.9, 死亡 0.00), set_transformer 10.7 (-59.3, 死亡 0.00), tabm 6.4 (-63.6, 死亡 0.00), ensemble 10.3 (-59.7, 死亡 0.00)

**GLORY / THE_LOST_AND_FORGOTTEN_NORMAL** (Monster; 怪物 THE_LOST, THE_FORGOTTEN) — mutation / mut-v1 / 构筑 `3087d2feb079`
- 牌组 31 张：ACROBATICS, ADRENALINE [SOULS_POWER 1], ASCENDERS_BANE, ASSASSINATE+1, CLOAK_AND_DAGGER×2, DECAY, DEFEND_SILENT×5, DODGE_AND_ROLL, EXPERTISE, EXPOSE, FAN_OF_KNIVES, FOOTWORK+1, HIDDEN_DAGGERS, INFINITE_BLADES+1, KNIFE_TRAP, LEG_SWEEP, PREP_TIME+1, STRIKE_SILENT×4, SURVIVOR, TORIC_TOUGHNESS, UNTOUCHABLE×2, UP_MY_SLEEVE
- 遗物 12 件：RING_OF_THE_SNAKE, HEFTY_TABLET, PLANISPHERE, PERMAFROST, JOSS_PAPER(CardsExhausted=2), ARCHAIC_TOOTH, GORGET, ODDLY_SMOOTH_STONE, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), BEATING_REMNANT, SNECKO_SKULL, IRON_CLUB(CardsPlayed=3)
- 变异：small / cards，改牌 2 改遗物 0，父代 `b716d1505a8f`
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 15.5 (-54.5, 死亡 0.00), repo_mlp 13.8 (-56.2, 死亡 0.00), rtdl_mlp 13.2 (-56.8, 死亡 0.00), rtdl_resnet 20.1 (-49.9, 死亡 0.00), set_transformer 14.8 (-55.2, 死亡 0.00), tabm 10.1 (-59.9, 死亡 0.00), ensemble 14.6 (-55.4, 死亡 0.00)

**HIVE / ENTOMANCER_ELITE** (Elite; 怪物 ENTOMANCER) — mutation / mut-v1 / 构筑 `80bfe36ddd61`
- 牌组 30 张：ADRENALINE+1, ASCENDERS_BANE, ASSASSINATE, BACKFLIP, DEFEND_SILENT×5, ESCAPE_PLAN+1, FLICK_FLACK, FOOTWORK, HAND_TRICK, NEUTRALIZE, PIERCING_WAIL+1, PREPARED, PREPARED+1, REFLEX+1×2, RICOCHET, SHOCKWAVE+1, STRIKE_SILENT×5, TACTICIAN+1, UNTOUCHABLE×2, WELL_LAID_PLANS [SWIFT 2]
- 遗物 10 件：RING_OF_THE_SNAKE, BOOMING_CONCH, HAPPY_FLOWER(TurnsSeen=0), GREMLIN_HORN, POTION_BELT, GHOST_SEED, PAELS_FLESH, ANCHOR, HORN_CLEAT, WING_CHARM
- 变异：small / both，改牌 2 改遗物 1，父代 `b585b9f23d1e`
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 16.3 (-53.7, 死亡 0.16), repo_mlp 9.6 (-60.4, 死亡 0.01), rtdl_mlp 25.9 (-44.1, 死亡 0.17), rtdl_resnet 10.8 (-59.2, 死亡 0.00), set_transformer 16.7 (-53.3, 死亡 0.06), tabm 20.8 (-49.2, 死亡 0.06), ensemble 16.7 (-53.3, 死亡 0.08)

**GLORY / QUEEN_BOSS** (Boss; 怪物 QUEEN, TORCH_HEAD_AMALGAM) — mutation / mut-v1 / 构筑 `c63d0c9299e4`
- 牌组 26 张：AFTERIMAGE+1, ASCENDERS_BANE, BACKFLIP, BUBBLE_BUBBLE+1×2, DEFEND_SILENT×4, DEFEND_SILENT+1, DEFLECT+1, DODGE_AND_ROLL+1, FOOTWORK+1, FOOTWORK+1 [SWIFT 2], HAND_TRICK+1, MAUL×5, MAUL+1, NOXIOUS_FUMES+1, PREPARED+1, REFLEX+1, SURVIVOR, UNTOUCHABLE+1
- 遗物 16 件：RING_OF_THE_SNAKE, GOLDEN_PEARL, GORGET, ORICHALCUM, MERCURY_HOURGLASS, PAPER_KRANE, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), ARCHAIC_TOOTH, HAPPY_FLOWER(TurnsSeen=0), JUZU_BRACELET, STRIKE_DUMMY, CLAWS, ICE_CREAM, SNECKO_SKULL, ODDLY_SMOOTH_STONE, WAR_PAINT
- 变异：large / cards，改牌 3 改遗物 0，父代 `07295b4d5f37`
- 标签（4 个种子净掉血）：[68, 70, 70, 70] → 均值 **69.5**，组内 std 1.0，死亡 3/4
- 预测（误差，死亡概率）：lightgbm 49.6 (-19.9, 死亡 0.14), repo_mlp 30.9 (-38.6, 死亡 0.05), rtdl_mlp 44.3 (-25.2, 死亡 0.21), rtdl_resnet 29.2 (-40.3, 死亡 0.02), set_transformer 16.9 (-52.6, 死亡 0.00), tabm 47.2 (-22.3, 死亡 0.28), ensemble 36.3 (-33.2, 死亡 0.12)

**HIVE / ENTOMANCER_ELITE** (Elite; 怪物 ENTOMANCER) — mutation / mut-v1 / 构筑 `2a967cbd7d9d`
- 牌组 30 张：ASCENDERS_BANE, ASSASSINATE, BACKFLIP, DEFEND_SILENT×5, ESCAPE_PLAN+1, FLECHETTES, FLICK_FLACK, FOOTWORK, NEUTRALIZE, PIERCING_WAIL+1, PREPARED+1×2, REFLEX+1×2, RICOCHET, SHOCKWAVE+1, STRIKE_SILENT×5, SURVIVOR, TACTICIAN+1, UNTOUCHABLE×2, WELL_LAID_PLANS [SWIFT 2]
- 遗物 9 件：RING_OF_THE_SNAKE, BOOMING_CONCH, HAPPY_FLOWER(TurnsSeen=0), POTION_BELT, GAME_PIECE, GHOST_SEED, PAELS_FLESH, ANCHOR, HORN_CLEAT
- 变异：small / both，改牌 1 改遗物 1，父代 `4d9426815205`
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 25.4 (-44.6, 死亡 0.27), repo_mlp 14.7 (-55.3, 死亡 0.03), rtdl_mlp 30.4 (-39.6, 死亡 0.16), rtdl_resnet 16.7 (-53.3, 死亡 0.01), set_transformer 18.1 (-51.9, 死亡 0.06), tabm 24.3 (-45.7, 死亡 0.08), ensemble 21.6 (-48.4, 死亡 0.10)

**HIVE / ENTOMANCER_ELITE** (Elite; 怪物 ENTOMANCER) — real / real-v3 / 构筑 `4d9426815205`
- 牌组 30 张：ASCENDERS_BANE, ASSASSINATE, BACKFLIP, DEFEND_SILENT×5, ESCAPE_PLAN+1, FLECHETTES, FLICK_FLACK, FOOTWORK, NEUTRALIZE, PIERCING_WAIL+1, PREPARED, PREPARED+1, REFLEX+1×2, RICOCHET, SHOCKWAVE+1, STRIKE_SILENT×5, SURVIVOR, TACTICIAN+1, UNTOUCHABLE×2, WELL_LAID_PLANS [SWIFT 2]
- 遗物 10 件：RING_OF_THE_SNAKE, BOOMING_CONCH, HAPPY_FLOWER(TurnsSeen=0), GREMLIN_HORN, POTION_BELT, GAME_PIECE, GHOST_SEED, PAELS_FLESH, ANCHOR, HORN_CLEAT
- 标签（4 个种子净掉血）：[70, 70, 70, 70] → 均值 **70.0**，组内 std 0.0，死亡 4/4
- 预测（误差，死亡概率）：lightgbm 20.4 (-49.6, 死亡 0.22), repo_mlp 15.9 (-54.1, 死亡 0.06), rtdl_mlp 29.8 (-40.2, 死亡 0.14), rtdl_resnet 22.3 (-47.7, 死亡 0.02), set_transformer 18.7 (-51.3, 死亡 0.07), tabm 24.0 (-46.0, 死亡 0.07), ensemble 21.9 (-48.1, 死亡 0.10)

**HIVE / MYTES_NORMAL** (Monster; 怪物 MYTE) — real / real-v4 / 构筑 `4499f0f0dd32`
- 牌组 16 张：ACCELERANT+1, ASCENDERS_BANE, CALCULATED_GAMBLE+1, DEFEND_SILENT×4, DEFEND_SILENT+1 [SPIRAL 1], LEG_SWEEP+1, NEUTRALIZE+1, STRIKE_SILENT×4, SUCKER_PUNCH+1, SURVIVOR+1
- 遗物 7 件：RING_OF_THE_SNAKE, NEW_LEAF, CAPTAINS_WHEEL, GORGET, AMETHYST_AUBERGINE, WAR_PAINT, PENDULUM(TurnsSeen=0)
- 标签（4 个种子净掉血）：[65, 34, 68, 70] → 均值 **59.2**，组内 std 17.0，死亡 1/4
- 预测（误差，死亡概率）：lightgbm 8.1 (-51.2, 死亡 0.00), repo_mlp 9.9 (-49.4, 死亡 0.00), rtdl_mlp 9.8 (-49.5, 死亡 0.00), rtdl_resnet 10.5 (-48.7, 死亡 0.00), set_transformer 8.3 (-51.0, 死亡 0.00), tabm 5.7 (-53.5, 死亡 0.00), ensemble 8.7 (-50.5, 死亡 0.00)

**GLORY / AEONGLASS_BOSS** (Boss; 怪物 AEONGLASS) — real / real-v4 / 构筑 `79978f8e09ea`
- 牌组 31 张：AFTERIMAGE, ASCENDERS_BANE, CLOAK_AND_DAGGER, CLOAK_AND_DAGGER+1, CLUMSY, DAGGER_THROW, DAGGER_THROW [SWIFT 2], DEFEND_SILENT×4, DEFLECT, FLICK_FLACK×3, NEUTRALIZE [SWIFT 2], PREPARED, PREPARED+1×2, PREPARED+1 [IMBUED 1], RICOCHET, RICOCHET [SWIFT 2]×2, SHADOW_STEP+1, SPEEDSTER+1, STRIKE_SILENT×3, SURVIVOR, TACTICIAN+1, ULTIMATE_STRIKE
- 遗物 19 件：RING_OF_THE_SNAKE, BAG_OF_MARBLES, VAJRA, CENTENNIAL_PUZZLE, BAG_OF_PREPARATION, ELECTRIC_SHRYMP, DAUGHTER_OF_THE_WIND, NUNCHAKU(AttacksPlayed=5), TUNING_FORK(SkillsPlayed=8), MERCURY_HOURGLASS, PARRYING_SHIELD, BEAUTIFUL_BRACELET, HISTORY_COURSE, VENERABLE_TEA_SET(GainEnergyInNextCombat=True), ODDLY_SMOOTH_STONE, SPARKLING_ROUGE, PENDULUM(TurnsSeen=0), POTION_BELT, LANTERN
- 标签（4 个种子净掉血）：[70, 70, 70, 53] → 均值 **65.8**，组内 std 8.5，死亡 3/4
- 预测（误差，死亡概率）：lightgbm 57.2 (-8.6, 死亡 0.63), repo_mlp 52.7 (-13.1, 死亡 0.37), rtdl_mlp 55.9 (-9.9, 死亡 0.57), rtdl_resnet 46.0 (-19.7, 死亡 0.32), set_transformer 15.0 (-50.8, 死亡 0.01), tabm 61.8 (-4.0, 死亡 0.74), ensemble 48.1 (-17.7, 死亡 0.44)

## 高掉血但预测准确

标签均值 ≥ 25 HP 且 |误差| ≤ 2 HP 的 pair。

**HIVE / DECIMILLIPEDE_ELITE** (Elite; 怪物 DECIMILLIPEDE_SEGMENT_FRONT, DECIMILLIPEDE_SEGMENT_MIDDLE, DECIMILLIPEDE_SEGMENT_BACK) — mutation / mut-v1 / 构筑 `9e60838e232e`
- 牌组 21 张：ABRASIVE, ACCELERANT+1, ASCENDERS_BANE, BACKFLIP, BACKSTAB+1, CLOAK_AND_DAGGER+1, DEFEND_SILENT×4, EXPOSE, HAZE, HIDDEN_DAGGERS, MEMENTO_MORI, NEUTRALIZE+1, PREPARED, RICOCHET+1, SNAKEBITE+1×2, SURVIVOR [NIMBLE 2], TOOLS_OF_THE_TRADE
- 遗物 8 件：RING_OF_THE_SNAKE, SILVER_CRUCIBLE(TimesUsed=2,TreasureRoomsEntered=0), LANTERN, VAMBRACE, NUNCHAKU(AttacksPlayed=3), BIIIG_HUG, SLING_OF_COURAGE, BING_BONG
- 变异：small / cards，改牌 1 改遗物 0，父代 `b16e4a50d1f9`
- 标签（4 个种子净掉血）：[13, 34, 47, 28] → 均值 **30.5**，组内 std 14.1，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 33.5 (+3.0, 死亡 0.02), repo_mlp 38.8 (+8.3, 死亡 0.02), rtdl_mlp 25.1 (-5.4, 死亡 0.00), rtdl_resnet 25.6 (-4.9, 死亡 0.00), set_transformer 31.3 (+0.8, 死亡 0.00), tabm 26.3 (-4.2, 死亡 0.01), ensemble 30.1 (-0.4, 死亡 0.01)

**OVERGROWTH / OVERGROWTH_CRAWLERS** (Monster; 怪物 SHRINKER_BEETLE, FUZZY_WURM_CRAWLER) — real / real-v3 / 构筑 `2afeea2c3edb`
- 牌组 19 张：ASCENDERS_BANE, BULLET_TIME, CLUMSY, DEFEND_SILENT×5, DEFLECT, ECHOING_SLASH, EXPERTISE, NEUTRALIZE, STRIKE_SILENT×5, SURVIVOR, UP_MY_SLEEVE
- 遗物 4 件：RING_OF_THE_SNAKE, NEOWS_BONES, BOOMING_CONCH, VEXING_PUZZLEBOX
- 标签（4 个种子净掉血）：[33, 38, 7, 28] → 均值 **26.5**，组内 std 13.6，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 21.5 (-5.0, 死亡 0.02), repo_mlp 11.8 (-14.7, 死亡 0.00), rtdl_mlp 22.6 (-3.9, 死亡 0.00), rtdl_resnet 11.3 (-15.2, 死亡 0.00), set_transformer 27.8 (+1.3, 死亡 0.00), tabm 18.8 (-7.7, 死亡 0.00), ensemble 19.0 (-7.5, 死亡 0.00)

**HIVE / DECIMILLIPEDE_ELITE** (Elite; 怪物 DECIMILLIPEDE_SEGMENT_FRONT, DECIMILLIPEDE_SEGMENT_MIDDLE, DECIMILLIPEDE_SEGMENT_BACK) — real / real-v3 / 构筑 `c0675d76f881`
- 牌组 30 张：ACCELERANT+1, ACCURACY, ASCENDERS_BANE, BOUNCING_FLASK+1, BULLET_TIME+1, CLUMSY, DASH, DEFEND_SILENT×5, DEFLECT, ESCAPE_PLAN, EXPERTISE+1, FLICK_FLACK×2, FOOTWORK+1 [SWIFT 2], HIDDEN_DAGGERS, HIDDEN_DAGGERS+1, LEADING_STRIKE, NEUTRALIZE+1, NOXIOUS_FUMES+1, PREPARED+1, REFLEX, SLICE, SNAKEBITE+1, STRIKE_SILENT×2, SURVIVOR
- 遗物 12 件：RING_OF_THE_SNAKE, GOLDEN_PEARL, SNECKO_SKULL, PENDULUM(TurnsSeen=2), WHITE_BEAST_STATUE, BLOOD_VIAL, BRONZE_SCALES, ASTROLABE, WAR_PAINT, PERMAFROST, TUNING_FORK(SkillsPlayed=2), POTION_BELT
- 标签（4 个种子净掉血）：[30, 24, 27, 40] → 均值 **30.2**，组内 std 6.9，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 23.2 (-7.0, 死亡 0.00), repo_mlp 34.0 (+3.8, 死亡 0.00), rtdl_mlp 22.8 (-7.4, 死亡 0.00), rtdl_resnet 33.2 (+2.9, 死亡 0.00), set_transformer 30.3 (+0.0, 死亡 0.00), tabm 23.3 (-6.9, 死亡 0.00), ensemble 27.8 (-2.4, 死亡 0.00)

**GLORY / QUEEN_BOSS** (Boss; 怪物 QUEEN, TORCH_HEAD_AMALGAM) — real / real-v4 / 构筑 `46133a9c1f15`
- 牌组 25 张：ASCENDERS_BANE, BURST+1, DEADLY_POISON+1, DEFEND_SILENT×3, DEFEND_SILENT+1, ESCAPE_PLAN×2, ESCAPE_PLAN [ADROIT 3], EXPOSE, FLECHETTES+1, FOOTWORK, HIDDEN_GEM+1 [ADROIT 3], NEUTRALIZE [ADROIT 3], NOXIOUS_FUMES+1, PIERCING_WAIL×2, PREPARED, SHADOWMELD+1, STRIKE_SILENT, STRIKE_SILENT+1×2, SURVIVOR, WELL_LAID_PLANS+1
- 遗物 17 件：RING_OF_THE_SNAKE, PRECARIOUS_SHEARS, LUCKY_FYSH, WAR_PAINT, TOASTY_MITTENS, KIFUDA, RIPPLE_BASIN, POTION_BELT, MR_STRUGGLES, CENTENNIAL_PUZZLE, MEAT_ON_THE_BONE, BRONZE_SCALES, GORGET, AMETHYST_AUBERGINE, RED_MASK, WHETSTONE, VAJRA
- 标签（4 个种子净掉血）：[5, 27, 70, 40] → 均值 **35.5**，组内 std 27.2，死亡 1/4
- 预测（误差，死亡概率）：lightgbm 28.2 (-7.3, 死亡 0.13), repo_mlp 50.8 (+15.3, 死亡 0.28), rtdl_mlp 35.5 (+0.0, 死亡 0.10), rtdl_resnet 52.6 (+17.1, 死亡 0.46), set_transformer 34.0 (-1.5, 死亡 0.07), tabm 47.9 (+12.4, 死亡 0.30), ensemble 41.5 (+6.0, 死亡 0.22)

**OVERGROWTH / BYGONE_EFFIGY_ELITE** (Elite; 怪物 BYGONE_EFFIGY) — real / real-v3 / 构筑 `c6bb8129393a`
- 牌组 17 张：ASCENDERS_BANE, CLOAK_AND_DAGGER, DEFEND_SILENT×3, EXPERTISE, FLICK_FLACK, NEUTRALIZE, PREDATOR, SIDESTEP, SKEWER, SLICE, SPEEDSTER, STRIKE_SILENT×3, SURVIVOR
- 遗物 1 件：RING_OF_THE_SNAKE
- 标签（4 个种子净掉血）：[48, 29, 37, 43] → 均值 **39.2**，组内 std 8.2，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 36.7 (-2.5, 死亡 0.01), repo_mlp 40.3 (+1.0, 死亡 0.00), rtdl_mlp 41.3 (+2.1, 死亡 0.00), rtdl_resnet 32.7 (-6.5, 死亡 0.00), set_transformer 40.3 (+1.0, 死亡 0.00), tabm 37.9 (-1.4, 死亡 0.01), ensemble 38.2 (-1.0, 死亡 0.00)

**OVERGROWTH / CEREMONIAL_BEAST_BOSS** (Boss; 怪物 CEREMONIAL_BEAST) — real / real-v4 / 构筑 `7892e71bcb1b`
- 牌组 22 张：ASCENDERS_BANE, DAGGER_THROW, DEFEND_SILENT×5, GUILTY {CombatsSeen=4}, JACK_OF_ALL_TRADES+1, LEADING_STRIKE, NEOWS_FURY, NEUTRALIZE+1, PHANTOM_BLADES, PREPARED, PREPARED+1, SIDESTEP, STRIKE_SILENT×3, STRIKE_SILENT+1, SURVIVOR, TORIC_TOUGHNESS
- 遗物 7 件：RING_OF_THE_SNAKE, NEOWS_BONES, NEOWS_TORMENT, LEAD_PAPERWEIGHT, TINGSHA, LASTING_CANDY(CombatRewardsSeen=0), ODDLY_SMOOTH_STONE
- 标签（4 个种子净掉血）：[28, 45, 44, 35] → 均值 **38.0**，组内 std 8.0，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 46.6 (+8.6, 死亡 0.06), repo_mlp 29.9 (-8.1, 死亡 0.01), rtdl_mlp 43.6 (+5.6, 死亡 0.10), rtdl_resnet 42.2 (+4.2, 死亡 0.02), set_transformer 37.4 (-0.6, 死亡 0.01), tabm 40.8 (+2.8, 死亡 0.07), ensemble 40.1 (+2.1, 死亡 0.04)

**GLORY / KNIGHTS_ELITE** (Elite; 怪物 FLAIL_KNIGHT, SPECTRAL_KNIGHT, MAGI_KNIGHT) — mutation / mut-v1 / 构筑 `52685e77d870`
- 牌组 25 张：ACCURACY+1, ASCENDERS_BANE, BACKFLIP, BLADE_DANCE, DAGGER_THROW, DEFEND_SILENT×4, EXPERTISE×2, HAND_TRICK [GLAM 1], HIDDEN_DAGGERS, KNIFE_TRAP+1, MALAISE, NEUTRALIZE+1, NOXIOUS_FUMES+1 [GLAM 1], PIERCING_WAIL+1 [GLAM 1], SQUASH+1, SURVIVOR, TACTICIAN+1, TOOLS_OF_THE_TRADE, TRACKING+1, UNTOUCHABLE [GLAM 1], UP_MY_SLEEVE+1
- 遗物 12 件：RING_OF_THE_SNAKE, LANTERN, ETERNAL_FEATHER, GORGET, VERY_HOT_COCOA, PANTOGRAPH, VENERABLE_TEA_SET(GainEnergyInNextCombat=True), VAMBRACE, GLITTER, HORN_CLEAT, LETTER_OPENER, MINIATURE_CANNON
- 变异：large / relics，改牌 0 改遗物 2，父代 `4adbf8a83739`
- 标签（4 个种子净掉血）：[70, 18, 5, 10] → 均值 **25.8**，组内 std 30.0，死亡 1/4
- 预测（误差，死亡概率）：lightgbm 26.7 (+0.9, 死亡 0.02), repo_mlp 42.0 (+16.3, 死亡 0.14), rtdl_mlp 37.0 (+11.2, 死亡 0.17), rtdl_resnet 42.9 (+17.1, 死亡 0.29), set_transformer 27.3 (+1.5, 死亡 0.09), tabm 32.7 (+7.0, 死亡 0.10), ensemble 34.8 (+9.0, 死亡 0.13)

**GLORY / DEVOTED_SCULPTOR_WEAK** (Monster, weak; 怪物 DEVOTED_SCULPTOR) — mutation / mut-v2 / 构筑 `8dbd50d38150`
- 牌组 27 张：ABRASIVE+1, AFTERIMAGE+1 [SWIFT 2], ASCENDERS_BANE, CALCULATED_GAMBLE+1, DEFEND_SILENT×4, DODGE_AND_ROLL+1, EQUILIBRIUM+1, EXPOSE, GREED, INFINITE_BLADES+1, LEADING_STRIKE, LEG_SWEEP, LEG_SWEEP+1, MASTER_PLANNER, NEUTRALIZE+1, PIERCING_WAIL, POISONED_STAB+1, PREPARED+1, SNAKEBITE+1, STRIKE_SILENT×4, SURVIVOR
- 遗物 12 件：RING_OF_THE_SNAKE, CURSED_PEARL, BRONZE_SCALES, BOWLER_HAT, VAMBRACE, TINGSHA, YUMMY_COOKIE, MINIATURE_TENT, CENTENNIAL_PUZZLE, GLITTER, GAMBLING_CHIP, TUNGSTEN_ROD
- 变异：large / relics，改牌 0 改遗物 2，父代 `5d58afcfa2b1`
- 标签（4 个种子净掉血）：[20, 23, 20, 54] → 均值 **29.2**，组内 std 16.6，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 8.1 (-21.2, 死亡 0.00), repo_mlp 21.5 (-7.8, 死亡 0.02), rtdl_mlp 22.6 (-6.7, 死亡 0.00), rtdl_resnet 23.7 (-5.6, 死亡 0.00), set_transformer 27.5 (-1.7, 死亡 0.04), tabm 16.5 (-12.8, 死亡 0.01), ensemble 20.0 (-9.3, 死亡 0.01)

## 随机典型样例

无筛选随机抽取，反映一般水平。

**OVERGROWTH / SNAPPING_JAXFRUIT_NORMAL** (Monster; 怪物 SNAPPING_JAXFRUIT, FLYCONID) — real / real-v3 / 构筑 `47fda46fd1d1`
- 牌组 15 张：ASCENDERS_BANE, DAGGER_SPRAY, DEFEND_SILENT×5, NEUTRALIZE, PREPARED, STRIKE_SILENT×5, SURVIVOR
- 遗物 2 件：RING_OF_THE_SNAKE, BOOMING_CONCH
- 标签（4 个种子净掉血）：[32, 21, 38, 39] → 均值 **32.5**，组内 std 8.3，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 28.2 (-4.3, 死亡 0.00), repo_mlp 21.8 (-10.7, 死亡 0.00), rtdl_mlp 22.9 (-9.6, 死亡 0.00), rtdl_resnet 23.1 (-9.4, 死亡 0.00), set_transformer 23.6 (-8.9, 死亡 0.00), tabm 25.2 (-7.3, 死亡 0.00), ensemble 24.1 (-8.4, 死亡 0.00)

**GLORY / AXEBOTS_NORMAL** (Monster; 怪物 AXEBOT) — mutation / mut-v2 / 构筑 `4f0b4bdd46da`
- 牌组 32 张：ABRASIVE, ACCELERANT, ACROBATICS, AFTERIMAGE+1, ASCENDERS_BANE, BACKSTAB, CLOAK_AND_DAGGER×2, DAGGER_THROW, DEADLY_POISON, DEFEND_SILENT×3, DEFEND_SILENT+1×2, DODGE_AND_ROLL+1, FAN_OF_KNIVES, FOOTWORK, LEADING_STRIKE, LEG_SWEEP, MIRAGE+1, NEUTRALIZE+1, PANIC_BUTTON+1, PHANTOM_BLADES, PIERCING_WAIL, POUNCE+1, SHADOWMELD, SQUASH+1, STRIKE_SILENT×2, SURVIVOR, UNTOUCHABLE
- 遗物 14 件：RING_OF_THE_SNAKE, LARGE_CAPSULE, TWISTED_FUNNEL, ORICHALCUM, WAR_PAINT, VAJRA, PAELS_LEGION, VENERABLE_TEA_SET(GainEnergyInNextCombat=False), BOWLER_HAT, JEWELRY_BOX, GORGET, SLING_OF_COURAGE, WHITE_BEAST_STATUE, TOXIC_EGG
- 变异：large / both，改牌 5 改遗物 4，父代 `54ccfaae11c6`
- 标签（4 个种子净掉血）：[32, 18, 43, 2] → 均值 **23.8**，组内 std 17.7，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 15.3 (-8.5, 死亡 0.00), repo_mlp 30.5 (+6.8, 死亡 0.00), rtdl_mlp 10.6 (-13.2, 死亡 0.00), rtdl_resnet 7.9 (-15.8, 死亡 0.00), set_transformer 12.5 (-11.3, 死亡 0.00), tabm 15.0 (-8.7, 死亡 0.00), ensemble 15.3 (-8.5, 死亡 0.00)

**GLORY / MECHA_KNIGHT_ELITE** (Elite; 怪物 MECHA_KNIGHT) — real / real-v3 / 构筑 `eb13eb61bd5f`
- 牌组 31 张：ABRASIVE+1, ACCELERANT+1, ADRENALINE+1, ASCENDERS_BANE, BACKFLIP+1×2, BACKSTAB, BUBBLE_BUBBLE, CALCULATED_GAMBLE+1, CLOAK_AND_DAGGER, DASH, DEADLY_POISON, DEFEND_SILENT×4, DEFEND_SILENT+1, DEFLECT, FOOTWORK+1×2, LEG_SWEEP, NEUTRALIZE, PIERCING_WAIL, PREPARED, PREPARED+1, SIDESTEP+1, SNAKEBITE+1, STRIKE_SILENT×2, SURVIVOR+1, WELL_LAID_PLANS+1
- 遗物 16 件：RING_OF_THE_SNAKE, SMALL_CAPSULE, PRAYER_WHEEL, GREMLIN_HORN, HAPPY_FLOWER(TurnsSeen=1), MEAT_ON_THE_BONE, PENDULUM(TurnsSeen=0), RADIANT_PEARL, GORGET, TOXIC_EGG, ODDLY_SMOOTH_STONE, PERMAFROST, THROWING_AXE, FAKE_ANCHOR, HORN_CLEAT, WAR_PAINT
- 标签（4 个种子净掉血）：[38, 39, 29, 24] → 均值 **32.5**，组内 std 7.2，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 14.8 (-17.7, 死亡 0.03), repo_mlp 13.4 (-19.1, 死亡 0.01), rtdl_mlp 9.4 (-23.1, 死亡 0.00), rtdl_resnet 3.6 (-28.9, 死亡 0.00), set_transformer 10.3 (-22.2, 死亡 0.00), tabm 13.8 (-18.7, 死亡 0.01), ensemble 10.9 (-21.6, 死亡 0.01)

**UNDERDOCKS / TWO_TAILED_RATS_NORMAL** (Monster; 怪物 TWO_TAILED_RAT) — real / real-v3 / 构筑 `ec6fbf25eac7`
- 牌组 18 张：ASCENDERS_BANE, BACKFLIP, DASH, DEFEND_SILENT×5, FOOTWORK, LEADING_STRIKE, NEUTRALIZE, PANACHE, STRIKE_SILENT×5, SURVIVOR
- 遗物 2 件：RING_OF_THE_SNAKE, LEAD_PAPERWEIGHT
- 标签（4 个种子净掉血）：[6, 15, 7, 7] → 均值 **8.8**，组内 std 4.2，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 8.3 (-0.4, 死亡 0.00), repo_mlp 5.3 (-3.4, 死亡 0.00), rtdl_mlp 3.3 (-5.5, 死亡 0.00), rtdl_resnet 3.1 (-5.7, 死亡 0.00), set_transformer 6.2 (-2.5, 死亡 0.00), tabm 4.2 (-4.6, 死亡 0.00), ensemble 5.1 (-3.7, 死亡 0.00)

**HIVE / HUNTER_KILLER_NORMAL** (Monster; 怪物 HUNTER_KILLER) — real / real-v3 / 构筑 `df7e543b6c63`
- 牌组 24 张：ASCENDERS_BANE, BACKFLIP+1, BLUR, CLOAK_AND_DAGGER+1×2, DEFEND_SILENT×5, EXPOSE+1, FOOTWORK+1 [SWIFT 2], LEADING_STRIKE, NEUTRALIZE+1, PHANTOM_BLADES×2, PREPARED+1, STRIKE_SILENT×5, SURVIVOR, WELL_LAID_PLANS
- 遗物 4 件：RING_OF_THE_SNAKE, SILVER_CRUCIBLE(TimesUsed=2,TreasureRoomsEntered=0), MINIATURE_CANNON, TOASTY_MITTENS
- 标签（4 个种子净掉血）：[20, 14, 13, 24] → 均值 **17.8**，组内 std 5.2，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 18.4 (+0.7, 死亡 0.00), repo_mlp 9.4 (-8.4, 死亡 0.00), rtdl_mlp 14.4 (-3.3, 死亡 0.00), rtdl_resnet 10.5 (-7.3, 死亡 0.00), set_transformer 12.1 (-5.7, 死亡 0.00), tabm 9.5 (-8.3, 死亡 0.00), ensemble 12.4 (-5.4, 死亡 0.00)

**OVERGROWTH / BYRDONIS_ELITE** (Elite; 怪物 BYRDONIS) — real / real-v4 / 构筑 `5fde0b31a825`
- 牌组 18 张：ACCURACY+1, ASCENDERS_BANE, BLADE_DANCE+1, CLOAK_AND_DAGGER+1×2, DEFEND_SILENT×5, FLICK_FLACK, NEUTRALIZE, STRIKE_SILENT×4, SURVIVOR, TORIC_TOUGHNESS
- 遗物 3 件：RING_OF_THE_SNAKE, SILVER_CRUCIBLE(TimesUsed=1,TreasureRoomsEntered=0), UNSETTLING_LAMP
- 标签（4 个种子净掉血）：[14, 6, 8, 20] → 均值 **12.0**，组内 std 6.3，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 16.7 (+4.7, 死亡 0.00), repo_mlp 15.7 (+3.7, 死亡 0.00), rtdl_mlp 15.8 (+3.8, 死亡 0.00), rtdl_resnet 15.3 (+3.3, 死亡 0.00), set_transformer 14.1 (+2.1, 死亡 0.00), tabm 14.6 (+2.6, 死亡 0.00), ensemble 15.4 (+3.4, 死亡 0.00)

**UNDERDOCKS / CORPSE_SLUGS_WEAK** (Monster, weak; 怪物 CORPSE_SLUG) — real / real-v3 / 构筑 `8d4109f49bbf`
- 牌组 16 张：ASCENDERS_BANE, DEFEND_SILENT×5, NEUTRALIZE, NOXIOUS_FUMES, PIERCING_WAIL, SCRAWL, STRIKE_SILENT×3, STRIKE_SILENT+1×2, SURVIVOR
- 遗物 2 件：RING_OF_THE_SNAKE, GOLDEN_PEARL
- 标签（4 个种子净掉血）：[0, 0, 1, 3] → 均值 **1.0**，组内 std 1.4，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 3.4 (+2.4, 死亡 0.00), repo_mlp 2.0 (+1.0, 死亡 0.00), rtdl_mlp 2.0 (+1.0, 死亡 0.00), rtdl_resnet 2.7 (+1.7, 死亡 0.00), set_transformer 2.6 (+1.6, 死亡 0.00), tabm 3.8 (+2.8, 死亡 0.00), ensemble 2.8 (+1.8, 死亡 0.00)

**HIVE / ENTOMANCER_ELITE** (Elite; 怪物 ENTOMANCER) — mutation / mut-v2 / 构筑 `9ef72dcaa310`
- 牌组 32 张：ADRENALINE+1×2, ASCENDERS_BANE, BACKFLIP, BACKSTAB, BLADE_DANCE×4, BRIGHTEST_FLAME+1, DAGGER_THROW, DEFEND_SILENT×4, DEFEND_SILENT+1, DODGE_AND_ROLL+1, FINISHER+1 [CORRUPTED 1], FLICK_FLACK, FOOTWORK+1, INFINITE_BLADES, KNIFE_TRAP+1, LEG_SWEEP, NEUTRALIZE, PREPARED+1, RICOCHET, STRIKE_SILENT×4, SURVIVOR, UP_MY_SLEEVE+1
- 遗物 12 件：RING_OF_THE_SNAKE, BOOMING_CONCH, SPARKLING_ROUGE, ETERNAL_FEATHER, GAME_PIECE, STORYBOOK, DOLLYS_MIRROR, JUZU_BRACELET, ODDLY_SMOOTH_STONE, GAMBLING_CHIP, PEN_NIB(AttacksPlayed=8), STRIKE_DUMMY
- 变异：small / cards，改牌 1 改遗物 0，父代 `70d655f1ebdb`
- 标签（4 个种子净掉血）：[21, 3, 26, 11] → 均值 **15.2**，组内 std 10.3，死亡 0/4
- 预测（误差，死亡概率）：lightgbm 20.5 (+5.3, 死亡 0.02), repo_mlp 4.7 (-10.5, 死亡 0.00), rtdl_mlp 3.2 (-12.1, 死亡 0.00), rtdl_resnet 4.1 (-11.2, 死亡 0.00), set_transformer 15.8 (+0.6, 死亡 0.00), tabm 7.0 (-8.2, 死亡 0.00), ensemble 9.2 (-6.0, 死亡 0.00)

