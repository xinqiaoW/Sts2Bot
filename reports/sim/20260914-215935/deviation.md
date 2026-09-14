# Simulator v0 deviation report — 20260914-215935

Human reference: 1629 held-out Silent A10 runs, of which 1208 were played to the end (the rest were quit early and only contribute floors, not outcomes). Fit split: 6401 runs, tables `sim-tables-v0`.
Arms: `sim/empirical/heuristic` = 2000 episodes (human damage histograms, heuristic policy); `sim/empirical/random` = 2000 episodes (human damage histograms, random policy); `sim/F/heuristic` = 2000 episodes (F ensemble of 6 (set_transformer, rtdl_resnet, tabm, rtdl_mlp, repo_mlp, lightgbm), pessimism=0.0, noise_sd=0.0, death_head=True, heuristic policy); `sim/F/greedy_f` = 500 episodes (same F oracle; card/smith/ancient choices by one-step F lookahead, map/shop heuristic).
Cells read `human → arm`; TV = total-variation distance between distributions (0 = identical, 1 = disjoint).

## 1. Run outcomes

| metric | human | sim/empirical/heuristic | sim/empirical/random | sim/F/heuristic | sim/F/greedy_f |
|---|---|---|---|---|---|
| completed runs | 1208 | 2000 | 2000 | 2000 | 500 |
| win rate % | 23.8 | 19.9 | 0.7 | 0.0 | 0.0 |
| floors reached mean | 29.6 | 32.3 | 17.6 | 12.9 | 19.4 |
| floors reached p25 / p50 / p75 | 16/30/48 | 16/32/48 | 12/16/16 | 7/12/16 | 12/16/29 |
| death in act 1 % | 47.4 | 34.8 | 76.1 | 89.3 | 63.0 |
| death in act 2 % | 34.2 | 35.3 | 20.5 | 10.3 | 32.0 |
| death in act 3 % | 18.3 | 30.0 | 3.4 | 0.3 | 5.0 |
| death room = monster % | 12.1 | 16.1 | 18.7 | 12.2 | 10.0 |
| death room = elite % | 35.8 | 33.6 | 39.8 | 52.0 | 36.0 |
| death room = boss % | 48.8 | 47.0 | 38.7 | 32.9 | 52.0 |
| death room = unknown % | 3.4 | 3.2 | 2.8 | 2.9 | 2.0 |
| death room = ancient % | 0.0 | 0.0 | 0.0 | 0.0 | 0.0 |

## 2. Trajectories by global floor (survivors only)

Floor 0 = act-1 ancient, 1–16 act 1 (boss at 16), 17–32 act 2, 33+ act 3.

**HP / max HP** (mean; arm cells show value and Δ vs human)

| floor | human | sim/empirical/heuristic | sim/empirical/random | sim/F/heuristic | sim/F/greedy_f |
|---|---|---|---|---|---|
| 1 | 0.75 (n=1469) | 0.75 (+0.00, n=2000) | 0.76 (+0.01, n=2000) | 0.76 (+0.01, n=1999) | 0.75 (-0.00, n=500) |
| 3 | 0.70 (n=1458) | 0.70 (-0.00, n=1999) | 0.70 (+0.00, n=1999) | 0.72 (+0.02, n=1999) | 0.72 (+0.01, n=499) |
| 6 | 0.58 (n=1378) | 0.64 (+0.06, n=1971) | 0.58 (-0.00, n=1961) | 0.61 (+0.03, n=1719) | 0.59 (+0.01, n=463) |
| 9 | 0.50 (n=1250) | 0.59 (+0.09, n=1909) | 0.47 (-0.03, n=1820) | 0.51 (+0.01, n=1252) | 0.50 (-0.00, n=408) |
| 12 | 0.52 (n=1160) | 0.59 (+0.07, n=1781) | 0.38 (-0.14, n=1483) | 0.52 (+0.00, n=984) | 0.50 (-0.01, n=372) |
| 16 | 0.30 (n=865) | 0.36 (+0.06, n=1443) | 0.25 (-0.05, n=488) | 0.16 (-0.14, n=214) | 0.17 (-0.12, n=185) |
| 17 | 0.85 (n=864) | 0.87 (+0.01, n=1443) | 0.84 (-0.01, n=488) | 0.83 (-0.03, n=214) | 0.83 (-0.02, n=185) |
| 20 | 0.71 (n=849) | 0.70 (-0.01, n=1436) | 0.68 (-0.03, n=482) | 0.64 (-0.07, n=213) | 0.64 (-0.07, n=185) |
| 25 | 0.55 (n=754) | 0.57 (+0.01, n=1324) | 0.45 (-0.10, n=414) | 0.46 (-0.09, n=120) | 0.47 (-0.08, n=154) |
| 30 | 0.44 (n=633) | 0.44 (-0.01, n=1072) | 0.29 (-0.15, n=206) | 0.35 (-0.09, n=70) | 0.35 (-0.09, n=103) |
| 33 | 0.87 (n=485) | 0.87 (+0.00, n=878) | 0.85 (-0.02, n=81) | 0.82 (-0.05, n=7) | 0.82 (-0.04, n=25) |
| 34 | 0.81 (n=481) | 0.80 (-0.01, n=878) | 0.79 (-0.03, n=80) | 0.73 (-0.08, n=7) | 0.76 (-0.06, n=25) |
| 38 | 0.69 (n=463) | 0.65 (-0.04, n=859) | 0.59 (-0.11, n=80) | 0.39 (-0.30, n=5) | 0.54 (-0.15, n=24) |
| 42 | 0.70 (n=443) | 0.62 (-0.09, n=824) | 0.48 (-0.22, n=71) | 0.34 (-0.36, n=3) | 0.54 (-0.17, n=23) |
| 46 | 0.85 (n=423) | 0.70 (-0.15, n=767) | 0.42 (-0.43, n=54) | 0.80 (-0.05, n=2) | 0.59 (-0.26, n=22) |
| 48 | 0.46 (n=284) | 0.32 (-0.13, n=398) | 0.24 (-0.21, n=13) | — | — |

**max HP** (mean; arm cells show value and Δ vs human)

| floor | human | sim/empirical/heuristic | sim/empirical/random | sim/F/heuristic | sim/F/greedy_f |
|---|---|---|---|---|---|
| 1 | 69.3 (n=1469) | 69.8 (+0.5, n=2000) | 69.7 (+0.4, n=2000) | 69.8 (+0.5, n=1999) | 69.6 (+0.3, n=500) |
| 3 | 69.1 (n=1458) | 69.9 (+0.8, n=1999) | 69.7 (+0.6, n=1999) | 69.8 (+0.7, n=1999) | 69.7 (+0.6, n=499) |
| 6 | 69.1 (n=1378) | 69.9 (+0.8, n=1971) | 69.7 (+0.6, n=1961) | 69.9 (+0.8, n=1719) | 69.9 (+0.8, n=463) |
| 9 | 69.6 (n=1250) | 70.4 (+0.8, n=1909) | 70.2 (+0.6, n=1820) | 70.6 (+1.0, n=1252) | 70.5 (+0.9, n=408) |
| 12 | 69.8 (n=1160) | 70.6 (+0.8, n=1781) | 70.5 (+0.7, n=1483) | 70.8 (+1.0, n=984) | 70.7 (+0.9, n=372) |
| 16 | 70.4 (n=865) | 71.4 (+1.1, n=1443) | 71.5 (+1.1, n=488) | 71.8 (+1.4, n=214) | 71.9 (+1.5, n=185) |
| 17 | 70.4 (n=864) | 71.4 (+1.1, n=1443) | 71.5 (+1.1, n=488) | 71.8 (+1.4, n=214) | 71.9 (+1.5, n=185) |
| 20 | 70.7 (n=849) | 71.8 (+1.1, n=1436) | 71.8 (+1.1, n=482) | 72.1 (+1.4, n=213) | 72.5 (+1.8, n=185) |
| 25 | 71.9 (n=754) | 73.0 (+1.1, n=1324) | 73.1 (+1.2, n=414) | 74.1 (+2.2, n=120) | 74.4 (+2.4, n=154) |
| 30 | 73.3 (n=633) | 74.3 (+1.0, n=1072) | 76.0 (+2.7, n=206) | 74.9 (+1.5, n=70) | 75.5 (+2.2, n=103) |
| 33 | 74.0 (n=485) | 75.5 (+1.5, n=878) | 77.3 (+3.3, n=81) | 74.1 (+0.2, n=7) | 80.5 (+6.5, n=25) |
| 34 | 73.6 (n=481) | 75.5 (+1.9, n=878) | 77.3 (+3.7, n=80) | 74.1 (+0.5, n=7) | 80.5 (+6.9, n=25) |
| 38 | 74.5 (n=463) | 77.0 (+2.5, n=859) | 79.0 (+4.5, n=80) | 72.4 (-2.1, n=5) | 82.8 (+8.3, n=24) |
| 42 | 75.7 (n=443) | 78.2 (+2.4, n=824) | 80.6 (+4.9, n=71) | 72.0 (-3.7, n=3) | 83.3 (+7.5, n=23) |
| 46 | 76.6 (n=423) | 79.1 (+2.5, n=767) | 83.6 (+7.0, n=54) | 69.5 (-7.1, n=2) | 83.9 (+7.3, n=22) |
| 48 | 76.7 (n=284) | 81.7 (+5.0, n=398) | 87.2 (+10.4, n=13) | — | — |

**gold** (mean; arm cells show value and Δ vs human)

| floor | human | sim/empirical/heuristic | sim/empirical/random | sim/F/heuristic | sim/F/greedy_f |
|---|---|---|---|---|---|
| 1 | 133 (n=1469) | 121 (-12, n=2000) | 121 (-12, n=2000) | 121 (-11, n=1999) | 110 (-23, n=500) |
| 3 | 122 (n=1458) | 125 (+4, n=1999) | 117 (-5, n=1999) | 127 (+6, n=1999) | 122 (+1, n=499) |
| 6 | 107 (n=1378) | 138 (+31, n=1971) | 120 (+13, n=1961) | 135 (+28, n=1719) | 131 (+24, n=463) |
| 9 | 150 (n=1250) | 186 (+36, n=1909) | 165 (+15, n=1820) | 175 (+25, n=1252) | 176 (+26, n=408) |
| 12 | 162 (n=1160) | 199 (+37, n=1781) | 171 (+9, n=1483) | 179 (+17, n=984) | 181 (+19, n=372) |
| 16 | 232 (n=865) | 268 (+36, n=1443) | 218 (-14, n=488) | 217 (-15, n=214) | 234 (+2, n=185) |
| 17 | 232 (n=864) | 268 (+35, n=1443) | 219 (-14, n=488) | 217 (-15, n=214) | 235 (+2, n=185) |
| 20 | 190 (n=849) | 243 (+53, n=1436) | 191 (+1, n=482) | 197 (+7, n=213) | 203 (+13, n=185) |
| 25 | 231 (n=754) | 252 (+21, n=1324) | 193 (-37, n=414) | 214 (-17, n=120) | 200 (-31, n=154) |
| 30 | 178 (n=633) | 216 (+38, n=1072) | 143 (-35, n=206) | 156 (-22, n=70) | 174 (-4, n=103) |
| 33 | 294 (n=485) | 295 (+1, n=878) | 214 (-79, n=81) | 173 (-121, n=7) | 230 (-63, n=25) |
| 34 | 310 (n=481) | 309 (-1, n=878) | 231 (-79, n=80) | 189 (-121, n=7) | 242 (-68, n=25) |
| 38 | 189 (n=463) | 230 (+41, n=859) | 149 (-40, n=80) | 88 (-101, n=5) | 201 (+12, n=24) |
| 42 | 199 (n=443) | 266 (+67, n=824) | 171 (-28, n=71) | 47 (-152, n=3) | 208 (+9, n=23) |
| 46 | 141 (n=423) | 227 (+86, n=767) | 165 (+23, n=54) | 54 (-87, n=2) | 185 (+44, n=22) |
| 48 | 141 (n=284) | 226 (+85, n=398) | 174 (+33, n=13) | — | — |

**deck size** (mean; arm cells show value and Δ vs human)

| floor | human | sim/empirical/heuristic | sim/empirical/random | sim/F/heuristic | sim/F/greedy_f |
|---|---|---|---|---|---|
| 1 | 14.6 (n=1469) | 14.2 (-0.4, n=2000) | 14.2 (-0.5, n=2000) | 14.2 (-0.4, n=1999) | 14.3 (-0.4, n=500) |
| 3 | 16.1 (n=1458) | 15.3 (-0.8, n=1999) | 15.1 (-1.0, n=1999) | 15.2 (-0.9, n=1999) | 15.6 (-0.5, n=499) |
| 6 | 17.9 (n=1378) | 16.6 (-1.3, n=1971) | 16.4 (-1.5, n=1961) | 16.6 (-1.3, n=1719) | 17.2 (-0.7, n=463) |
| 9 | 18.9 (n=1250) | 17.5 (-1.4, n=1909) | 17.3 (-1.6, n=1820) | 17.4 (-1.5, n=1252) | 18.2 (-0.7, n=408) |
| 12 | 20.2 (n=1160) | 18.6 (-1.6, n=1781) | 18.4 (-1.8, n=1483) | 18.6 (-1.6, n=984) | 19.7 (-0.5, n=372) |
| 16 | 22.5 (n=865) | 20.6 (-1.9, n=1443) | 20.1 (-2.4, n=488) | 20.7 (-1.8, n=214) | 21.8 (-0.7, n=185) |
| 17 | 22.5 (n=864) | 20.6 (-2.0, n=1443) | 20.1 (-2.4, n=488) | 20.6 (-2.0, n=214) | 21.8 (-0.7, n=185) |
| 20 | 24.3 (n=849) | 22.3 (-2.0, n=1436) | 21.9 (-2.4, n=482) | 22.5 (-1.8, n=213) | 23.7 (-0.6, n=185) |
| 25 | 26.0 (n=754) | 24.1 (-1.8, n=1324) | 23.9 (-2.1, n=414) | 23.9 (-2.1, n=120) | 25.1 (-0.8, n=154) |
| 30 | 28.1 (n=633) | 26.3 (-1.8, n=1072) | 26.1 (-1.9, n=206) | 25.8 (-2.3, n=70) | 26.8 (-1.3, n=103) |
| 33 | 29.0 (n=485) | 27.5 (-1.5, n=878) | 26.2 (-2.9, n=81) | 26.6 (-2.4, n=7) | 27.6 (-1.4, n=25) |
| 34 | 29.7 (n=481) | 28.3 (-1.4, n=878) | 26.9 (-2.7, n=80) | 27.3 (-2.4, n=7) | 28.2 (-1.5, n=25) |
| 38 | 32.4 (n=463) | 30.2 (-2.2, n=859) | 29.1 (-3.4, n=80) | 30.4 (-2.0, n=5) | 29.9 (-2.5, n=24) |
| 42 | 33.3 (n=443) | 31.2 (-2.1, n=824) | 29.9 (-3.4, n=71) | 30.3 (-3.0, n=3) | 30.7 (-2.7, n=23) |
| 46 | 34.9 (n=423) | 32.6 (-2.4, n=767) | 31.2 (-3.7, n=54) | 31.5 (-3.4, n=2) | 31.4 (-3.6, n=22) |
| 48 | 35.1 (n=284) | 32.8 (-2.3, n=398) | 32.0 (-3.1, n=13) | — | — |

**relic count** (mean; arm cells show value and Δ vs human)

| floor | human | sim/empirical/heuristic | sim/empirical/random | sim/F/heuristic | sim/F/greedy_f |
|---|---|---|---|---|---|
| 1 | 2.2 (n=1469) | 2.0 (-0.2, n=2000) | 2.0 (-0.2, n=2000) | 2.0 (-0.2, n=1999) | 2.0 (-0.2, n=500) |
| 3 | 2.4 (n=1458) | 2.2 (-0.2, n=1999) | 2.2 (-0.2, n=1999) | 2.2 (-0.2, n=1999) | 2.2 (-0.2, n=499) |
| 6 | 2.8 (n=1378) | 2.6 (-0.2, n=1971) | 2.5 (-0.3, n=1961) | 2.5 (-0.3, n=1719) | 2.5 (-0.3, n=463) |
| 9 | 4.4 (n=1250) | 4.1 (-0.2, n=1909) | 4.1 (-0.3, n=1820) | 4.0 (-0.4, n=1252) | 4.0 (-0.4, n=408) |
| 12 | 5.2 (n=1160) | 4.9 (-0.3, n=1781) | 4.7 (-0.5, n=1483) | 4.6 (-0.6, n=984) | 4.6 (-0.6, n=372) |
| 16 | 6.2 (n=865) | 5.5 (-0.7, n=1443) | 5.1 (-1.1, n=488) | 5.3 (-0.9, n=214) | 5.3 (-0.9, n=185) |
| 17 | 7.3 (n=864) | 6.5 (-0.8, n=1443) | 6.1 (-1.2, n=488) | 6.3 (-1.0, n=214) | 6.3 (-1.0, n=185) |
| 20 | 7.7 (n=849) | 6.8 (-0.9, n=1436) | 6.3 (-1.4, n=482) | 6.7 (-1.0, n=213) | 6.6 (-1.1, n=185) |
| 25 | 9.7 (n=754) | 8.9 (-0.9, n=1324) | 8.2 (-1.5, n=414) | 8.7 (-1.0, n=120) | 8.7 (-1.0, n=154) |
| 30 | 11.9 (n=633) | 10.4 (-1.5, n=1072) | 9.5 (-2.3, n=206) | 10.0 (-1.9, n=70) | 10.1 (-1.7, n=103) |
| 33 | 13.1 (n=485) | 11.3 (-1.8, n=878) | 10.4 (-2.7, n=81) | 11.6 (-1.5, n=7) | 12.2 (-0.9, n=25) |
| 34 | 13.1 (n=481) | 11.3 (-1.8, n=878) | 10.3 (-2.7, n=80) | 11.6 (-1.5, n=7) | 12.2 (-0.9, n=25) |
| 38 | 14.2 (n=463) | 12.2 (-2.0, n=859) | 11.0 (-3.2, n=80) | 12.8 (-1.4, n=5) | 13.0 (-1.2, n=24) |
| 42 | 16.4 (n=443) | 14.3 (-2.1, n=824) | 13.0 (-3.4, n=71) | 15.7 (-0.8, n=3) | 14.7 (-1.7, n=23) |
| 46 | 17.9 (n=423) | 15.4 (-2.4, n=767) | 14.0 (-3.9, n=54) | 17.0 (-0.9, n=2) | 15.7 (-2.1, n=22) |
| 48 | 18.3 (n=284) | 15.4 (-2.8, n=398) | 13.9 (-4.3, n=13) | — | — |

| metric | human | sim/empirical/heuristic | sim/empirical/random | sim/F/heuristic | sim/F/greedy_f |
|---|---|---|---|---|---|
| deck size after act 1 boss | 22.5 | 20.6 | 20.1 | 20.7 | 21.8 |
| relics after act 1 boss | 6.2 | 5.5 | 5.1 | 5.3 | 5.3 |
| deck size after act 2 boss | 28.9 | 27.2 | 25.9 | 25.7 | 26.9 |
| relics after act 2 boss | 12.1 | 10.3 | 9.4 | 10.6 | 11.2 |
| deck size after act 3 boss | 35.2 | 32.8 | 32 | — | — |
| relics after act 3 boss | 18.4 | 15.4 | 13.9 | — | — |

## 3. Map structure

Visited node type per act and floor (TV distance human vs arm; floors with TV ≥ 0.15 listed).

| act | floor | sim/empirical/heuristic | sim/empirical/random | sim/F/heuristic | sim/F/greedy_f |
|---|---|---|---|---|---|
| OVERGROWTH | mean TV over floors | 0.077 | 0.064 | 0.080 | 0.091 |
| OVERGROWTH | floor 7 | 0.131 | 0.129 | 0.168 | 0.104 |
| OVERGROWTH |   ↳ sim/empirical/heuristic | monster: 23.1→27.9, unknown: 20.7→29.1, elite: 25.0→24.7, rest_site: 27.9→15.3, shop: 3.2→3.1 |  |  |  |
| OVERGROWTH | floor 11 | 0.168 | 0.172 | 0.148 | 0.195 |
| OVERGROWTH |   ↳ sim/empirical/heuristic | elite: 30.5→24.9, unknown: 16.3→29.9, monster: 21.0→24.3, rest_site: 27.8→16.7, shop: 4.3→4.2 |  |  |  |
| OVERGROWTH | floor 12 | 0.124 | 0.148 | 0.104 | 0.165 |
| OVERGROWTH |   ↳ sim/empirical/heuristic | rest_site: 47.3→37.1, unknown: 15.5→24.8, monster: 16.4→19.6, elite: 16.6→14.5, shop: 4.1→4.0 |  |  |  |
| OVERGROWTH | floor 14 | 0.142 | 0.127 | 0.158 | 0.203 |
| OVERGROWTH |   ↳ sim/empirical/heuristic | elite: 37.5→25.3, monster: 25.2→35.9, unknown: 26.1→29.6, shop: 11.2→9.2 |  |  |  |
| UNDERDOCKS | mean TV over floors | 0.074 | 0.060 | 0.076 | 0.077 |
| UNDERDOCKS | floor 7 | 0.148 | 0.138 | 0.154 | 0.139 |
| UNDERDOCKS |   ↳ sim/empirical/heuristic | elite: 26.2→28.6, unknown: 19.7→28.6, rest_site: 29.4→15.8, monster: 20.4→23.9, shop: 4.3→3.2 |  |  |  |
| UNDERDOCKS | floor 11 | 0.154 | 0.176 | 0.159 | 0.160 |
| UNDERDOCKS |   ↳ sim/empirical/heuristic | elite: 29.8→24.7, monster: 21.4→26.6, rest_site: 28.5→18.2, unknown: 16.8→25.5, shop: 3.5→5.1 |  |  |  |
| UNDERDOCKS | floor 14 | 0.169 | 0.122 | 0.122 | 0.132 |
| UNDERDOCKS |   ↳ sim/empirical/heuristic | monster: 28.0→35.2, elite: 39.0→22.0, unknown: 23.3→32.8, shop: 9.7→10.0 |  |  |  |
| HIVE | mean TV over floors | 0.081 | 0.060 | 0.085 | 0.078 |
| HIVE | floor 7 | 0.224 | 0.211 | 0.248 | 0.203 |
| HIVE |   ↳ sim/empirical/heuristic | rest_site: 39.7→17.8, elite: 25.4→31.8, unknown: 17.6→28.0, monster: 11.8→17.3, shop: 5.6→5.2 |  |  |  |
| HIVE | floor 10 | 0.174 | 0.172 | 0.201 | 0.158 |
| HIVE |   ↳ sim/empirical/heuristic | elite: 29.4→27.5, unknown: 17.2→29.5, rest_site: 28.0→14.3, monster: 17.9→22.4, shop: 5.7→6.4, treasure: 1.8→0.0 |  |  |  |
| HIVE | floor 13 | 0.165 | 0.096 | 0.189 | 0.122 |
| HIVE |   ↳ sim/empirical/heuristic | elite: 38.7→22.2, unknown: 23.0→33.1, monster: 25.1→30.8, shop: 13.2→13.9 |  |  |  |
| GLORY | mean TV over floors | 0.059 | 0.057 | 0.286 | 0.105 |
| GLORY | floor 2 | 0.045 | 0.056 | 0.449 | 0.009 |
| GLORY |   ↳ sim/empirical/heuristic | unknown: 43.1→47.6, monster: 40.8→38.4, shop: 16.0→14.0 |  |  |  |
| GLORY | floor 5 | 0.101 | 0.053 | 0.324 | 0.183 |
| GLORY |   ↳ sim/empirical/heuristic | monster: 51.0→42.5, unknown: 33.7→43.8, shop: 15.4→13.6 |  |  |  |
| GLORY | floor 6 | 0.064 | 0.103 | 0.418 | 0.067 |
| GLORY |   ↳ sim/empirical/heuristic | rest_site: 58.2→55.8, elite: 21.0→26.4, unknown: 13.6→12.3, shop: 5.4→2.8, monster: 1.7→2.7 |  |  |  |
| GLORY | floor 8 | 0.034 | 0.087 | 0.549 | 0.153 |
| GLORY |   ↳ sim/empirical/heuristic | rest_site: 45.0→48.1, elite: 25.9→24.2, unknown: 16.6→15.9, monster: 7.3→7.7, shop: 5.1→4.1 |  |  |  |
| GLORY | floor 9 | 0.132 | 0.095 | 0.537 | 0.358 |
| GLORY |   ↳ sim/empirical/heuristic | elite: 31.8→30.4, unknown: 20.1→29.0, rest_site: 25.7→14.0, monster: 14.5→18.9, shop: 7.8→7.8 |  |  |  |
| GLORY | floor 10 | 0.094 | 0.133 | 0.511 | 0.251 |
| GLORY |   ↳ sim/empirical/heuristic | rest_site: 46.3→44.2, unknown: 15.6→22.1, elite: 20.5→14.6, monster: 9.7→12.6, shop: 7.9→6.6 |  |  |  |
| GLORY | floor 11 | 0.078 | 0.073 | 0.450 | 0.214 |
| GLORY |   ↳ sim/empirical/heuristic | unknown: 26.7→33.9, monster: 27.9→28.4, elite: 28.3→24.5, shop: 17.1→13.1 |  |  |  |
| GLORY | floor 12 | 0.155 | 0.105 | 0.780 | 0.171 |
| GLORY |   ↳ sim/empirical/heuristic | elite: 39.6→25.5, unknown: 24.5→35.7, monster: 22.0→26.3, shop: 13.9→12.5 |  |  |  |

Unknown-room resolution (`?` nodes):

| act | TV (sim/empirical/heuristic) | human → sim/empirical/heuristic |
|---|---|---|
| OVERGROWTH | 0.019 | event: 69.4→69.7, monster: 19.0→20.4, shop: 5.3→5.5, treasure: 4.9→4.4, event+monster: 1.5→0.0 |
| UNDERDOCKS | 0.009 | event: 71.0→71.1, monster: 17.9→18.5, shop: 6.0→5.5, treasure: 4.7→4.9, event+monster: 0.5→0.0 |
| HIVE | 0.015 | event: 73.8→73.5, monster: 16.2→17.6, shop: 5.0→4.7, treasure: 4.1→4.2, event+monster: 0.9→0.0 |
| GLORY | 0.071 | event: 71.1→69.7, monster: 15.3→21.6, shop: 4.3→4.2, treasure: 3.8→4.5, event+monster: 5.5→0.0 |

## 4. Encounter pools

| act | room | TV sim/empirical/heuristic | TV sim/empirical/random | TV sim/F/heuristic | TV sim/F/greedy_f | human → sim/empirical/heuristic (top 4) |
|---|---|---|---|---|---|---|
| OVERGROWTH | monster | 0.054 | 0.054 | 0.043 | 0.051 | SHRINKER_BEETLE_WEAK: 15.7→14.7, SLIMES_WEAK: 15.2→14.3, NIBBITS_WEAK: 15.5→13.7, FUZZY_WURM_CRAWLER_WEAK: 14.6→14.1 |
| OVERGROWTH | elite | 0.009 | 0.012 | 0.023 | 0.023 | PHROG_PARASITE_ELITE: 33.8→34.0, BYGONE_EFFIGY_ELITE: 32.8→33.5, BYRDONIS_ELITE: 33.5→32.5 |
| OVERGROWTH | boss | 0.013 | 0.021 | 0.030 | 0.004 | CEREMONIAL_BEAST_BOSS: 34.2→35.5, VANTOM_BOSS: 33.0→32.2, THE_KIN_BOSS: 32.8→32.3 |
| UNDERDOCKS | monster | 0.055 | 0.053 | 0.023 | 0.049 | SLUDGE_SPINNER_WEAK: 15.2→15.0, TOADPOLES_WEAK: 15.4→14.0, CORPSE_SLUGS_WEAK: 15.2→14.1, SEAPUNK_WEAK: 15.8→13.3 |
| UNDERDOCKS | elite | 0.036 | 0.024 | 0.037 | 0.034 | PHANTASMAL_GARDENERS_ELITE: 34.8→34.6, TERROR_EEL_ELITE: 32.7→36.3, SKULKING_COLONY_ELITE: 32.5→29.1 |
| UNDERDOCKS | boss | 0.055 | 0.057 | 0.047 | 0.078 | SOUL_FYSH_BOSS: 35.5→34.2, LAGAVULIN_MATRIARCH_BOSS: 29.9→35.4, WATERFALL_GIANT_BOSS: 34.6→30.4 |
| HIVE | monster | 0.035 | 0.043 | 0.058 | 0.046 | EXOSKELETONS_WEAK: 12.7→11.4, TUNNELER_WEAK: 11.9→11.3, BOWLBUGS_WEAK: 11.2→11.3, THIEVING_HOPPER_WEAK: 11.6→10.8 |
| HIVE | elite | 0.014 | 0.031 | 0.012 | 0.025 | INFESTED_PRISMS_ELITE: 33.3→34.1, ENTOMANCER_ELITE: 34.1→32.7, DECIMILLIPEDE_ELITE: 32.6→33.2 |
| HIVE | boss | 0.050 | 0.065 | 0.082 | 0.036 | KAISER_CRAB_BOSS: 38.2→33.2, THE_INSATIABLE_BOSS: 32.4→32.4, KNOWLEDGE_DEMON_BOSS: 29.4→34.4 |
| GLORY | monster | 0.048 | 0.059 | 0.152 | 0.114 | DEVOTED_SCULPTOR_WEAK: 18.0→15.5, SCROLLS_OF_BITING_WEAK: 17.0→15.0, TURRET_OPERATOR_WEAK: 15.7→16.3, FABRICATOR_NORMAL: 5.9→6.4 |
| GLORY | elite | 0.019 | 0.038 | 0.322 | 0.047 | KNIGHTS_ELITE: 35.0→33.1, SOUL_NEXUS_ELITE: 32.7→33.6, MECHA_KNIGHT_ELITE: 32.2→33.3 |
| GLORY | boss | 0.030 | 0.030 | 0.325 | 0.045 | TEST_SUBJECT_BOSS: 35.5→32.7, AEONGLASS_BOSS: 32.4→34.1, QUEEN_BOSS: 32.0→33.3, DOORMAKER_BOSS: 0.1→0.0 |

Share of `_WEAK` encounters by fight index within the act (human → first arm):

| act | fight 0 | fight 1 | fight 2 | fight 3 | fight 4 | fight 5 |
|---|---|---|---|---|---|---|
| OVERGROWTH | 100→100 | 100→100 | 100→100 | 0→0 | 0→0 | 0→0 |
| UNDERDOCKS | 100→100 | 100→100 | 100→100 | 0→0 | 0→0 | 0→0 |
| HIVE | 100→100 | 100→100 | 0→0 | 0→0 | 0→0 | 0→0 |
| GLORY | 100→100 | 100→100 | 0→0 | 0→0 | 0→0 | 0→0 |

## 5. Rewards

Gold gained per room (mean / median; Δ mean):

| act | room | human | sim/empirical/heuristic | sim/empirical/random | sim/F/heuristic | sim/F/greedy_f |
|---|---|---|---|---|---|---|
| OVERGROWTH | monster | 11.3 / 11 | 11.3 / 11 (+0.0) | 11.3 / 11 (-0.1) | 11.2 / 11 (-0.1) | 11.1 / 11 (-0.2) |
| OVERGROWTH | elite | 30.9 / 30 | 30.4 / 30 (-0.5) | 30.4 / 30 (-0.5) | 30.3 / 30 (-0.6) | 30.5 / 30 (-0.5) |
| OVERGROWTH | boss | 76.6 / 75 | 75.0 / 75 (-1.6) | 75.0 / 75 (-1.6) | 75.0 / 75 (-1.6) | 75.0 / 75 (-1.6) |
| OVERGROWTH | treasure | 33.4 / 35 | 32.7 / 35 (-0.6) | 32.8 / 35 (-0.6) | 33.3 / 35 (-0.1) | 33.5 / 35 (+0.1) |
| UNDERDOCKS | monster | 11.4 / 11 | 11.2 / 11 (-0.2) | 11.3 / 11 (-0.1) | 11.2 / 11 (-0.2) | 11.3 / 11 (-0.1) |
| UNDERDOCKS | elite | 31.2 / 30 | 30.6 / 30 (-0.6) | 30.7 / 30 (-0.5) | 30.7 / 30 (-0.5) | 30.0 / 30 (-1.2) |
| UNDERDOCKS | boss | 77.5 / 75 | 75.0 / 75 (-2.5) | 75.0 / 75 (-2.5) | 75.0 / 75 (-2.5) | 75.0 / 75 (-2.5) |
| UNDERDOCKS | treasure | 34.1 / 35 | 33.4 / 35 (-0.7) | 33.4 / 35 (-0.7) | 33.6 / 35 (-0.5) | 32.8 / 35 (-1.3) |
| HIVE | monster | 12.9 / 12 | 12.8 / 12 (-0.1) | 12.8 / 12 (-0.1) | 12.7 / 11 (-0.2) | 12.8 / 11 (-0.0) |
| HIVE | elite | 34.1 / 31 | 32.2 / 30 (-1.9) | 31.9 / 30 (-2.2) | 31.1 / 29 (-3.0) | 32.1 / 30 (-2.0) |
| HIVE | boss | 79.1 / 75 | 75.0 / 75 (-4.1) | 75.0 / 75 (-4.1) | 75.0 / 75 (-4.1) | 75.0 / 75 (-4.1) |
| HIVE | treasure | 89.0 / 36 | 35.2 / 35 (-53.7) | 35.1 / 35 (-53.9) | 35.4 / 36 (-53.5) | 35.3 / 35 (-53.7) |
| GLORY | monster | 14.0 / 12 | 13.9 / 12 (-0.1) | 14.5 / 13 (+0.6) | 14.3 / 12 (+0.4) | 13.9 / 12 (-0.1) |
| GLORY | elite | 33.3 / 31 | 33.0 / 31 (-0.3) | 32.4 / 30 (-0.9) | 28.0 / 28 (-5.3) | 33.3 / 32 (+0.0) |
| GLORY | boss | 0.0 / 0 | 0.0 / 0 (-0.0) | 0.0 / 0 (-0.0) | 0.0 / 0 (-0.0) | 0.0 / 0 (-0.0) |
| GLORY | treasure | 35.5 / 36 | 35.5 / 36 (+0.1) | 35.0 / 35 (-0.5) | 35.4 / 36 (-0.1) | 35.7 / 36 (+0.2) |

| metric | human | sim/empirical/heuristic | sim/empirical/random | sim/F/heuristic | sim/F/greedy_f |
|---|---|---|---|---|---|
| card options = 3, monster % | 95.8 | 100.0 | 100.0 | 100.0 | 100.0 |
| card options = 3, elite % | 94.4 | 100.0 | 100.0 | 100.0 | 100.0 |
| card options = 3, boss % | 96.3 | 100.0 | 100.0 | 100.0 | 100.0 |
| card picked, monster % | 78.0 | 78.1 | 75.5 | 78.0 | 92.4 |
| card picked, elite % | 74.5 | 73.1 | 74.9 | 74.7 | 89.4 |
| card picked, boss % | 91.2 | 91.5 | 75.2 | 88.7 | 91.4 |
| card rarity TV GLORY:elite | 0 | 0.012 | 0.032 | 0.118 | 0.048 |
|   ↳ GLORY:elite | Common: 52.0→52.3, Uncommon: 38.2→39.1, Rare: 9.8→8.6 |  |  |  |  |
| card rarity TV GLORY:monster | 0 | 0.006 | 0.036 | 0.137 | 0.022 |
|   ↳ GLORY:monster | Common: 62.1→62.7, Uncommon: 37.0→36.5, Rare: 0.9→0.8 |  |  |  |  |
| card rarity TV HIVE:boss | 0 | 0.001 | 0.001 | 0.001 | 0.001 |
|   ↳ HIVE:boss | Rare: 99.9→100.0, Common: 0.1→0.0 |  |  |  |  |
| card rarity TV HIVE:elite | 0 | 0.006 | 0.003 | 0.026 | 0.039 |
|   ↳ HIVE:elite | Common: 52.6→52.4, Uncommon: 39.3→39.9, Rare: 8.1→7.7 |  |  |  |  |
| card rarity TV HIVE:monster | 0 | 0.012 | 0.011 | 0.026 | 0.021 |
|   ↳ HIVE:monster | Common: 63.2→62.1, Uncommon: 35.8→37.1, Rare: 0.9→0.8 |  |  |  |  |
| card rarity TV OVERGROWTH:boss | 0 | 0.000 | 0.000 | 0.000 | 0.000 |
|   ↳ OVERGROWTH:boss | Rare: 100.0→100.0 |  |  |  |  |
| card rarity TV OVERGROWTH:elite | 0 | 0.007 | 0.013 | 0.030 | 0.042 |
|   ↳ OVERGROWTH:elite | Common: 53.2→53.9, Uncommon: 39.9→39.7, Rare: 6.9→6.4 |  |  |  |  |
| card rarity TV OVERGROWTH:monster | 0 | 0.012 | 0.011 | 0.010 | 0.013 |
|   ↳ OVERGROWTH:monster | Common: 62.5→63.7, Uncommon: 36.3→35.2, Rare: 1.1→1.1 |  |  |  |  |
| card rarity TV UNDERDOCKS:boss | 0 | 0.003 | 0.004 | 0.003 | 0.000 |
|   ↳ UNDERDOCKS:boss | Rare: 100.0→99.7, Common: 0.0→0.1, Uncommon: 0.0→0.1 |  |  |  |  |
| card rarity TV UNDERDOCKS:elite | 0 | 0.008 | 0.008 | 0.007 | 0.008 |
|   ↳ UNDERDOCKS:elite | Common: 53.8→53.0, Uncommon: 40.1→40.3, Rare: 6.1→6.7 |  |  |  |  |
| card rarity TV UNDERDOCKS:monster | 0 | 0.004 | 0.002 | 0.003 | 0.003 |
|   ↳ UNDERDOCKS:monster | Common: 62.9→63.3, Uncommon: 35.9→35.7, Rare: 1.1→1.0 |  |  |  |  |
| relic rarity TV elite | 0 | 0.002 | 0.011 | 0.025 | 0.009 |
|   ↳ elite | Common: 49.0→49.1, Uncommon: 33.8→33.8, Rare: 17.3→17.1 |  |  |  |  |
| relic rarity TV treasure | 0 | 0.010 | 0.015 | 0.019 | 0.014 |
|   ↳ treasure | Common: 50.7→49.7, Uncommon: 31.9→32.4, Rare: 17.3→17.9 |  |  |  |  |

## 6. Rest sites, shops, events

| metric | human | sim/empirical/heuristic | sim/empirical/random | sim/F/heuristic | sim/F/greedy_f |
|---|---|---|---|---|---|
| rest choice TV | 0 | 0.149 | 0.367 | 0.254 | 0.168 |
|   ↳ rest choice | SMITH: 56.8→43.8, HEAL: 41.3→56.2, LIFT: 0.4→0.0, DIG: 0.4→0.0 |  |  |  |  |
| heal amount / max HP (mean) | 0.320 | 0.298 | 0.279 | 0.298 | 0.298 |
| shop gold spent mean / p50 | 191 / 151 | 155 / 100 | 120 / 100 | 106 / 100 | 115 / 100 |
| shop stock size TV | 0 | 0.031 | 0.028 | 0.032 | 0.033 |
| shop visits buying a card % | 22.2 | 15.1 | 16.6 | 14.3 | 15.0 |
| shop visits buying a relic % | 11.6 | 8.9 | 1.1 | 5.2 | 5.9 |
| shop visits buying a purge % | 11.4 | 12.6 | 17.6 | 11.7 | 11.1 |

Event frequency TV per act and the events whose mean ΔHP deviates most (human → first arm):

| act | metric | TV sim/empirical/heuristic | TV sim/empirical/random | TV sim/F/heuristic | TV sim/F/greedy_f | top events |
|---|---|---|---|---|---|---|
| OVERGROWTH | frequency TV | 0.049 | 0.050 | 0.071 | 0.090 | BRAIN_LEECH: 6.8→6.7, ROOM_FULL_OF_CHEESE: 6.5→6.1, JUNGLE_MAZE_ADVENTURE: 6.2→6.2, WELLSPRING: 6.2→6.2 |
| UNDERDOCKS | frequency TV | 0.039 | 0.044 | 0.043 | 0.073 | DROWNING_BEACON: 7.6→8.2, BRAIN_LEECH: 7.5→7.6, THIS_OR_THAT: 7.3→7.7, SUNKEN_TREASURY: 7.3→7.1 |
| HIVE | frequency TV | 0.077 | 0.089 | 0.117 | 0.119 | DOLL_ROOM: 5.5→5.2, POTION_COURIER: 4.8→5.2, LOST_WISP: 4.1→5.8, COLORFUL_PHILOSOPHERS: 4.7→4.8 |
| GLORY | frequency TV | 0.068 | 0.100 | 0.557 | 0.196 | TINKER_TIME: 7.8→8.1, HUNGRY_FOR_MUSHROOMS: 8.4→7.2, ROUND_TEA_PARTY: 7.8→7.5, TRIAL: 7.2→7.5 |

| event | ΔHP human | ΔHP sim/empirical/heuristic | Δgold human | Δgold sim/empirical/heuristic | n human | n sim/empirical/heuristic |
|---|---|---|---|---|---|---|
| HUNGRY_FOR_MUSHROOMS | -4.2 | +2.4 | +0.0 | +0.0 | 76 | 145 |
| UNREST_SITE | +11.3 | +7.4 | +0.0 | +0.2 | 39 | 77 |
| ROUND_TEA_PARTY | -7.6 | -4.9 | +0.0 | +2.0 | 70 | 152 |
| ENDLESS_CONVEYOR | +8.0 | +10.2 | -90.5 | -79.1 | 47 | 77 |
| SPIRIT_GRAFTER | -2.4 | -0.4 | +0.0 | +0.2 | 79 | 166 |
| STONE_OF_ALL_TIME | +3.4 | +5.4 | +0.0 | +0.0 | 76 | 146 |
| JUNGLE_MAZE_ADVENTURE | -6.3 | -4.3 | +84.0 | +75.5 | 92 | 170 |
| REFLECTIONS | +1.8 | +0.4 | +7.8 | +0.0 | 56 | 116 |
| COLOSSAL_FLOWER | -8.6 | -7.5 | +36.3 | +39.9 | 79 | 176 |
| TRASH_HEAP | -3.6 | -4.6 | +55.1 | +43.0 | 102 | 180 |
| SAPPHIRE_SEED | +4.2 | +5.2 | +0.0 | +0.0 | 93 | 161 |
| DOLL_ROOM | -3.8 | -4.6 | +0.0 | +0.0 | 96 | 194 |

## 7. Combat outcomes per encounter

Mean HP lost per fight: human (holdout, includes potions and player skill) vs each arm; `F mean` is the model oracle's expected loss before noise/death sampling; `teacher` is the mean CombatSolver label on real human builds from the training snapshot. Death % = fights that ended the run.

| act | encounter | n human | human HP lost | human death % | sim/empirical/heuristic (Δ) / death | sim/empirical/random (Δ) / death | sim/F/heuristic (Δ) / death | sim/F/greedy_f (Δ) / death | F mean | teacher |
|---|---|---|---|---|---|---|---|---|---|---|
| OVERGROWTH | SHRINKER_BEETLE_WEAK | 553 | 1.9 | 0.0 | 2.1 (+0.2) / 0.1% | 2.0 (+0.1) / 0.0% | 1.8 (-0.1) / 0.0% | 1.7 (-0.2) / 0.0% | 1.8 | 1.7 |
| OVERGROWTH | NIBBITS_WEAK | 546 | 2.6 | 0.0 | 2.8 (+0.2) / 0.3% | 2.5 (-0.1) / 0.0% | 1.7 (-0.9) / 0.1% | 1.6 (-1.0) / 0.0% | 1.6 | 1.5 |
| OVERGROWTH | SLIMES_WEAK | 537 | 2.8 | 0.0 | 2.7 (-0.1) / 0.0% | 2.8 (+0.0) / 0.1% | 1.7 (-1.1) / 0.0% | 1.6 (-1.2) / 0.0% | 1.7 | 1.7 |
| OVERGROWTH | FUZZY_WURM_CRAWLER_WEAK | 514 | 2.5 | 0.0 | 2.5 (+0.1) / 0.1% | 2.5 (+0.0) / 0.0% | 2.1 (-0.3) / 0.3% | 1.8 (-0.7) / 0.0% | 2.1 | 1.4 |
| OVERGROWTH | PHROG_PARASITE_ELITE | 454 | 14.0 | 7.5 | 13.4 (-0.6) / 6.1% | 12.3 (-1.6) / 16.7% | 32.5 (+18.6) / 52.7% | 23.0 (+9.0) / 22.5% | 41.4 | 23.9 |
| OVERGROWTH | BYRDONIS_ELITE | 450 | 16.5 | 5.6 | 15.3 (-1.2) / 7.3% | 14.2 (-2.3) / 19.7% | 32.4 (+15.9) / 29.5% | 23.7 (+7.3) / 20.2% | 36.0 | 21.9 |
| OVERGROWTH | BYGONE_EFFIGY_ELITE | 441 | 17.7 | 9.3 | 17.0 (-0.8) / 8.9% | 14.5 (-3.3) / 18.8% | 33.4 (+15.6) / 44.5% | 26.1 (+8.4) / 12.3% | 39.9 | 22.9 |
| OVERGROWTH | CEREMONIAL_BEAST_BOSS | 178 | 26.0 | 17.4 | 25.0 (-1.0) / 11.8% | 17.1 (-8.9) / 54.9% | 40.2 (+14.2) / 65.4% | 34.2 (+8.2) / 32.7% | 50.6 | 37.6 |
| OVERGROWTH | VANTOM_BOSS | 172 | 28.7 | 14.5 | 24.7 (-4.0) / 15.3% | 17.0 (-11.7) / 57.1% | 41.2 (+12.5) / 59.4% | 34.2 (+5.5) / 41.2% | 47.8 | 35.2 |
| OVERGROWTH | THE_KIN_BOSS | 171 | 30.1 | 24.0 | 26.5 (-3.6) / 11.8% | 17.3 (-12.8) / 51.1% | 41.9 (+11.8) / 83.9% | 37.6 (+7.5) / 66.7% | 57.6 | 43.5 |
| OVERGROWTH | VINE_SHAMBLER_NORMAL | 138 | 6.3 | 0.7 | 6.3 (+0.0) / 3.6% | 6.5 (+0.2) / 2.6% | 7.7 (+1.4) / 3.7% | 6.6 (+0.3) / 5.4% | 7.5 | 5.6 |
| OVERGROWTH | RUBY_RAIDERS_NORMAL | 135 | 7.2 | 4.4 | 8.4 (+1.3) / 3.3% | 8.7 (+1.5) / 8.4% | 14.5 (+7.3) / 8.3% | 11.4 (+4.3) / 7.8% | 15.0 | 11.2 |
| OVERGROWTH | INKLETS_NORMAL | 133 | 6.1 | 0.0 | 6.2 (+0.1) / 2.0% | 5.0 (-1.1) / 4.1% | 8.1 (+1.9) / 3.7% | 7.7 (+1.6) / 1.9% | 8.2 | 6.5 |
| OVERGROWTH | CUBEX_CONSTRUCT_NORMAL | 132 | 4.9 | 1.5 | 4.2 (-0.7) / 0.9% | 4.4 (-0.5) / 7.1% | 8.4 (+3.5) / 4.2% | 5.2 (+0.3) / 0.0% | 8.5 | 5.4 |
| OVERGROWTH | MAWLER_NORMAL | 118 | 6.0 | 1.7 | 5.8 (-0.2) / 1.6% | 6.2 (+0.2) / 6.0% | 9.3 (+3.3) / 5.0% | 7.4 (+1.4) / 7.3% | 9.4 | 6.8 |
| OVERGROWTH | NIBBITS_NORMAL | 117 | 9.7 | 2.6 | 9.4 (-0.3) / 6.0% | 8.8 (-0.9) / 11.7% | 15.1 (+5.3) / 21.4% | 10.8 (+1.0) / 0.0% | 16.8 | 12.7 |
| OVERGROWTH | FOGMOG_NORMAL | 111 | 5.4 | 1.8 | 5.3 (-0.2) / 1.5% | 6.0 (+0.6) / 5.5% | 9.1 (+3.7) / 3.2% | 4.3 (-1.1) / 0.0% | 9.3 | 5.9 |
| OVERGROWTH | OVERGROWTH_CRAWLERS | 106 | 10.5 | 4.7 | 9.2 (-1.3) / 4.0% | 8.0 (-2.5) / 10.0% | 25.8 (+15.3) / 32.8% | 16.6 (+6.1) / 3.0% | 30.0 | 17.3 |
| OVERGROWTH | SNAPPING_JAXFRUIT_NORMAL | 103 | 11.0 | 1.9 | 11.3 (+0.4) / 4.8% | 9.4 (-1.6) / 9.0% | 17.5 (+6.6) / 10.7% | 13.5 (+2.6) / 2.3% | 18.3 | 13.2 |
| OVERGROWTH | FLYCONID_NORMAL | 101 | 10.6 | 1.0 | 9.3 (-1.3) / 5.6% | 8.0 (-2.6) / 8.9% | 12.5 (+1.9) / 6.1% | 11.1 (+0.5) / 0.0% | 12.7 | 10.6 |
| OVERGROWTH | SLIMES_NORMAL | 93 | 5.8 | 0.0 | 7.2 (+1.4) / 2.5% | 5.8 (+0.0) / 5.1% | 10.1 (+4.3) / 4.6% | 6.4 (+0.6) / 0.0% | 10.4 | 7.0 |
| OVERGROWTH | SLITHERING_STRANGLER_NORMAL | 92 | 7.4 | 2.2 | 8.6 (+1.2) / 6.4% | 6.9 (-0.5) / 8.2% | 8.9 (+1.5) / 3.0% | 4.6 (-2.8) / 0.0% | 9.0 | 5.2 |
| UNDERDOCKS | SEAPUNK_WEAK | 560 | 3.1 | 0.0 | 3.3 (+0.2) / 0.3% | 3.0 (-0.1) / 0.1% | 2.3 (-0.7) / 0.0% | 2.0 (-1.0) / 0.0% | 2.3 | 2.0 |
| UNDERDOCKS | TOADPOLES_WEAK | 546 | 4.3 | 0.0 | 4.3 (+0.1) / 0.1% | 4.4 (+0.1) / 0.4% | 3.1 (-1.1) / 0.0% | 2.8 (-1.5) / 0.0% | 3.1 | 2.7 |
| UNDERDOCKS | SLUDGE_SPINNER_WEAK | 539 | 2.8 | 0.0 | 3.0 (+0.2) / 0.0% | 2.9 (+0.1) / 0.0% | 2.3 (-0.5) / 0.0% | 2.1 (-0.6) / 0.0% | 2.3 | 2.3 |
| UNDERDOCKS | CORPSE_SLUGS_WEAK | 537 | 5.0 | 0.0 | 4.5 (-0.5) / 0.0% | 4.8 (-0.2) / 0.1% | 4.0 (-1.0) / 0.1% | 3.5 (-1.5) / 0.0% | 4.0 | 3.4 |
| UNDERDOCKS | PHANTASMAL_GARDENERS_ELITE | 468 | 14.7 | 5.6 | 14.7 (+0.1) / 7.3% | 12.7 (-1.9) / 16.1% | 34.4 (+19.7) / 50.9% | 26.1 (+11.4) / 25.2% | 42.2 | 25.7 |
| UNDERDOCKS | TERROR_EEL_ELITE | 439 | 18.1 | 9.1 | 17.6 (-0.5) / 9.7% | 14.5 (-3.6) / 21.2% | 31.8 (+13.7) / 45.0% | 25.7 (+7.6) / 17.6% | 38.7 | 22.3 |
| UNDERDOCKS | SKULKING_COLONY_ELITE | 436 | 14.4 | 4.1 | 13.8 (-0.6) / 4.1% | 13.0 (-1.4) / 18.5% | 23.1 (+8.8) / 14.3% | 19.2 (+4.8) / 9.1% | 24.4 | 15.3 |
| UNDERDOCKS | SOUL_FYSH_BOSS | 190 | 24.5 | 14.2 | 22.6 (-1.9) / 8.2% | 15.4 (-9.2) / 55.3% | 40.8 (+16.2) / 74.4% | 33.8 (+9.3) / 41.5% | 51.8 | 36.4 |
| UNDERDOCKS | WATERFALL_GIANT_BOSS | 185 | 27.9 | 20.0 | 25.1 (-2.8) / 10.8% | 15.7 (-12.2) / 58.0% | 43.0 (+15.1) / 83.2% | 36.1 (+8.2) / 55.6% | 57.8 | 41.4 |
| UNDERDOCKS | LAGAVULIN_MATRIARCH_BOSS | 160 | 21.7 | 18.8 | 24.0 (+2.3) / 12.0% | 14.8 (-7.0) / 55.4% | 41.8 (+20.1) / 74.5% | 33.0 (+11.3) / 43.1% | 55.3 | 39.9 |
| UNDERDOCKS | SEWER_CLAM_NORMAL | 152 | 3.9 | 0.7 | 4.5 (+0.6) / 1.4% | 4.7 (+0.8) / 3.9% | 6.1 (+2.2) / 2.4% | 3.7 (-0.2) / 0.0% | 6.1 | 3.5 |
| UNDERDOCKS | CULTISTS_NORMAL | 149 | 7.5 | 4.7 | 8.5 (+1.0) / 3.1% | 8.0 (+0.4) / 8.4% | 21.1 (+13.6) / 25.0% | 12.9 (+5.4) / 9.1% | 23.1 | 16.1 |
| UNDERDOCKS | HAUNTED_SHIP_NORMAL | 138 | 6.3 | 0.0 | 6.6 (+0.3) / 2.7% | 6.1 (-0.2) / 6.9% | 10.3 (+4.0) / 4.1% | 6.7 (+0.4) / 8.5% | 10.5 | 7.4 |
| UNDERDOCKS | LIVING_FOG_NORMAL | 138 | 8.2 | 3.6 | 7.8 (-0.4) / 1.4% | 7.8 (-0.4) / 9.2% | 7.2 (-1.1) / 4.7% | 5.5 (-2.8) / 0.0% | 7.2 | 5.6 |
| UNDERDOCKS | GREMLIN_MERC_NORMAL | 137 | 5.9 | 2.2 | 5.8 (-0.0) / 2.4% | 5.7 (-0.1) / 8.5% | 9.7 (+3.8) / 5.5% | 8.4 (+2.6) / 3.7% | 9.9 | 7.4 |
| UNDERDOCKS | FOSSIL_STALKER_NORMAL | 136 | 4.5 | 0.0 | 4.9 (+0.5) / 1.4% | 4.9 (+0.4) / 4.4% | 8.6 (+4.1) / 2.4% | 8.2 (+3.7) / 1.7% | 8.7 | 6.0 |
| UNDERDOCKS | PUNCH_CONSTRUCT_NORMAL | 133 | 6.1 | 1.5 | 6.2 (+0.1) / 1.7% | 5.4 (-0.7) / 7.1% | 7.6 (+1.5) / 2.2% | 6.4 (+0.3) / 1.6% | 7.6 | 5.9 |
| UNDERDOCKS | SEAPUNK_NORMAL | 133 | 10.2 | 6.8 | 8.7 (-1.6) / 2.6% | 7.8 (-2.4) / 8.2% | 19.7 (+9.5) / 12.7% | 15.4 (+5.2) / 2.9% | 20.9 | 13.6 |
| UNDERDOCKS | TWO_TAILED_RATS_NORMAL | 131 | 5.6 | 2.3 | 5.4 (-0.3) / 0.7% | 5.0 (-0.6) / 3.9% | 11.1 (+5.5) / 5.6% | 7.2 (+1.6) / 1.7% | 11.2 | 7.7 |
| UNDERDOCKS | CORPSE_SLUGS_NORMAL | 109 | 7.2 | 2.8 | 6.4 (-0.8) / 2.0% | 6.3 (-0.8) / 4.5% | 11.0 (+3.8) / 5.4% | 7.8 (+0.6) / 3.6% | 11.1 | 7.2 |
| HIVE | ENTOMANCER_ELITE | 476 | 16.5 | 7.8 | 16.3 (-0.2) / 11.8% | 14.8 (-1.7) / 21.4% | 28.3 (+11.8) / 50.0% | 19.8 (+3.3) / 10.1% | 35.0 | 20.0 |
| HIVE | INFESTED_PRISMS_ELITE | 464 | 21.3 | 8.0 | 20.1 (-1.3) / 12.4% | 18.6 (-2.7) / 32.1% | 32.7 (+11.3) / 40.5% | 25.7 (+4.4) / 25.7% | 39.5 | 24.5 |
| HIVE | EXOSKELETONS_WEAK | 462 | 3.3 | 0.0 | 3.1 (-0.3) / 0.0% | 3.4 (+0.0) / 0.0% | 2.7 (-0.6) / 0.0% | 2.3 (-1.1) / 0.0% | 2.8 | 2.1 |
| HIVE | DECIMILLIPEDE_ELITE | 455 | 17.1 | 10.1 | 16.7 (-0.4) / 9.2% | 14.2 (-2.9) / 27.2% | 33.4 (+16.3) / 63.8% | 28.3 (+11.2) / 40.0% | 42.2 | 26.9 |
| HIVE | TUNNELER_WEAK | 432 | 6.6 | 0.2 | 6.8 (+0.2) / 0.0% | 7.0 (+0.4) / 0.0% | 9.7 (+3.1) / 0.0% | 7.7 (+1.1) / 0.0% | 9.8 | 6.9 |
| HIVE | THIEVING_HOPPER_WEAK | 420 | 5.4 | 0.0 | 6.3 (+1.0) / 0.0% | 6.0 (+0.6) / 0.0% | 4.6 (-0.8) / 0.0% | 4.4 (-1.0) / 0.0% | 4.6 | 3.5 |
| HIVE | BOWLBUGS_WEAK | 406 | 5.0 | 0.2 | 4.9 (-0.1) / 0.0% | 5.0 (-0.0) / 0.4% | 4.9 (-0.2) / 0.0% | 4.6 (-0.4) / 0.0% | 4.9 | 3.9 |
| HIVE | KAISER_CRAB_BOSS | 235 | 31.8 | 22.1 | 29.1 (-2.8) / 21.6% | 18.6 (-13.2) / 64.8% | 41.8 (+10.0) / 95.2% | 40.3 (+8.5) / 82.1% | 58.3 | 44.4 |
| HIVE | SPINY_TOAD_NORMAL | 219 | 8.3 | 3.7 | 8.3 (+0.0) / 3.4% | 8.3 (+0.0) / 11.1% | 10.3 (+2.0) / 8.1% | 8.7 (+0.4) / 7.3% | 10.8 | 7.5 |
| HIVE | HUNTER_KILLER_NORMAL | 202 | 11.8 | 3.5 | 12.5 (+0.8) / 6.3% | 12.1 (+0.3) / 13.0% | 17.4 (+5.7) / 8.6% | 15.8 (+4.0) / 6.7% | 18.7 | 12.8 |
| HIVE | MYTES_NORMAL | 201 | 8.7 | 3.5 | 8.2 (-0.5) / 4.9% | 8.3 (-0.4) / 8.5% | 13.2 (+4.5) / 4.5% | 12.3 (+3.6) / 8.3% | 13.6 | 10.6 |
| HIVE | CHOMPERS_NORMAL | 199 | 9.8 | 3.5 | 9.2 (-0.6) / 3.2% | 9.5 (-0.3) / 10.8% | 14.1 (+4.3) / 10.5% | 10.7 (+0.9) / 4.5% | 15.2 | 10.8 |
| HIVE | THE_INSATIABLE_BOSS | 199 | 23.7 | 20.1 | 23.6 (-0.2) / 15.6% | 15.2 (-8.6) / 62.3% | 45.6 (+21.9) / 84.0% | 41.8 (+18.0) / 76.7% | 57.0 | 46.9 |
| HIVE | THE_OBSCURA_NORMAL | 194 | 7.3 | 3.1 | 7.7 (+0.4) / 5.6% | 6.0 (-1.3) / 3.4% | 15.7 (+8.4) / 8.8% | 10.4 (+3.2) / 6.9% | 16.8 | 9.8 |
| HIVE | OVICOPTER_NORMAL | 191 | 5.8 | 1.6 | 7.9 (+2.1) / 2.2% | 8.9 (+3.1) / 10.3% | 15.7 (+9.9) / 14.6% | 10.0 (+4.3) / 6.7% | 16.8 | 10.6 |
| HIVE | LOUSE_PROGENITOR_NORMAL | 182 | 7.5 | 0.5 | 7.7 (+0.2) / 3.8% | 8.4 (+0.9) / 4.3% | 14.1 (+6.5) / 10.3% | 8.7 (+1.2) / 2.3% | 14.7 | 8.0 |
| HIVE | KNOWLEDGE_DEMON_BOSS | 181 | 27.8 | 22.7 | 26.4 (-1.4) / 17.1% | 16.0 (-11.7) / 55.4% | 49.4 (+21.6) / 91.7% | 41.6 (+13.9) / 67.6% | 63.3 | 46.3 |
| HIVE | SLUMBERING_BEETLE_NORMAL | 180 | 11.1 | 6.1 | 10.8 (-0.3) / 5.3% | 11.6 (+0.5) / 14.3% | 20.0 (+8.9) / 11.1% | 16.0 (+4.9) / 11.1% | 21.7 | 14.3 |
| HIVE | EXOSKELETONS_NORMAL | 175 | 4.6 | 1.1 | 6.3 (+1.7) / 2.6% | 5.3 (+0.7) / 3.5% | 7.4 (+2.7) / 0.0% | 7.5 (+2.9) / 3.0% | 7.3 | 5.8 |
| HIVE | BOWLBUGS_NORMAL | 163 | 6.0 | 4.3 | 6.7 (+0.7) / 2.0% | 6.1 (+0.1) / 10.3% | 11.3 (+5.3) / 11.4% | 11.0 (+5.0) / 6.1% | 12.6 | 8.2 |
| GLORY | DEVOTED_SCULPTOR_WEAK | 340 | 5.8 | 0.3 | 5.7 (-0.1) / 0.0% | 6.9 (+1.1) / 1.9% | 8.5 (+2.7) / 0.0% | 6.3 (+0.5) / 0.0% | 8.6 | 7.1 |
| GLORY | SCROLLS_OF_BITING_WEAK | 322 | 3.0 | 0.3 | 3.1 (+0.2) / 0.0% | 4.9 (+2.0) / 0.0% | 7.0 (+4.0) / 0.0% | 4.4 (+1.5) / 0.0% | 7.0 | 4.2 |
| GLORY | TURRET_OPERATOR_WEAK | 297 | 4.4 | 0.3 | 4.8 (+0.4) / 0.2% | 4.1 (-0.3) / 0.0% | 7.0 (+2.6) / 0.0% | 4.7 (+0.2) / 0.0% | 7.3 | 4.2 |
| GLORY | TEST_SUBJECT_BOSS | 273 | 25.9 | 18.7 | 23.1 (-2.8) / 24.7% | 22.2 (-3.7) / 50.0% | 50.5 (+24.6) / 50.0% | 37.5 (+11.6) / 75.0% | 59.3 | 48.7 |
| GLORY | KNIGHTS_ELITE | 260 | 12.7 | 5.0 | 12.4 (-0.3) / 5.7% | 11.6 (-1.1) / 12.2% | 49.3 (+36.6) / 66.7% | 25.7 (+12.9) / 0.0% | 47.1 | 25.7 |
| GLORY | AEONGLASS_BOSS | 249 | 27.5 | 19.7 | 23.6 (-3.9) / 28.8% | 18.2 (-9.4) / 36.7% | — | 39.3 (+11.8) / 77.8% | — | 52.2 |
| GLORY | QUEEN_BOSS | 246 | 23.2 | 11.8 | 20.4 (-2.8) / 24.0% | 13.0 (-10.2) / 46.9% | 10.0 (-13.2) / 100.0% | 32.3 (+9.1) / 66.7% | 56.6 | 45.9 |
| GLORY | SOUL_NEXUS_ELITE | 243 | 10.5 | 2.1 | 12.5 (+2.0) / 2.9% | 10.5 (-0.0) / 15.2% | 10.5 (-0.0) / 50.0% | 16.9 (+6.3) / 0.0% | 24.2 | 14.8 |
| GLORY | MECHA_KNIGHT_ELITE | 239 | 15.3 | 3.3 | 17.1 (+1.7) / 8.2% | 14.9 (-0.4) / 25.6% | — | 23.3 (+8.0) / 22.2% | — | 23.4 |
| GLORY | SLIMED_BERSERKER_NORMAL | 114 | 4.5 | 0.9 | 6.2 (+1.7) / 2.7% | 8.1 (+3.6) / 3.4% | 7.0 (+2.5) / 0.0% | 9.8 (+5.3) / 0.0% | 6.8 | 8.7 |
| GLORY | FABRICATOR_NORMAL | 112 | 6.7 | 1.8 | 6.9 (+0.2) / 2.1% | 6.2 (-0.5) / 0.0% | 16.0 (+9.3) / 0.0% | 6.5 (-0.2) / 0.0% | 15.9 | 8.6 |
| GLORY | CONSTRUCT_MENAGERIE_NORMAL | 111 | 7.4 | 3.6 | 9.2 (+1.8) / 3.8% | 7.6 (+0.2) / 0.0% | 22.3 (+15.0) / 33.3% | 16.2 (+8.8) / 0.0% | 25.9 | 14.4 |
| GLORY | OWL_MAGISTRATE_NORMAL | 108 | 6.0 | 1.9 | 6.4 (+0.4) / 2.3% | 8.0 (+2.0) / 4.3% | 12.5 (+6.5) / 0.0% | 8.5 (+2.5) / 8.3% | 12.6 | 8.4 |
| GLORY | THE_LOST_AND_FORGOTTEN_NORMAL | 104 | 6.0 | 0.0 | 6.6 (+0.5) / 0.9% | 6.5 (+0.5) / 0.0% | 17.5 (+11.5) / 50.0% | 11.7 (+5.6) / 0.0% | 19.3 | 10.6 |
| GLORY | FROG_KNIGHT_NORMAL | 102 | 6.4 | 1.0 | 5.8 (-0.6) / 3.1% | 8.4 (+2.0) / 0.0% | 11.0 (+4.6) / 0.0% | 4.8 (-1.6) / 0.0% | 10.9 | 6.4 |
| GLORY | GLOBE_HEAD_NORMAL | 100 | 7.2 | 2.0 | 6.3 (-1.0) / 1.3% | 5.0 (-2.2) / 6.2% | 7.0 (-0.2) / 0.0% | 4.7 (-2.5) / 0.0% | 6.9 | 6.3 |
| GLORY | SCROLLS_OF_BITING_NORMAL | 92 | 4.3 | 2.2 | 4.4 (+0.2) / 1.0% | 8.9 (+4.7) / 0.0% | 20.0 (+15.7) / 0.0% | 10.2 (+5.9) / 0.0% | 20.5 | 8.5 |
| GLORY | AXEBOTS_NORMAL | 92 | 7.0 | 1.1 | 7.8 (+0.8) / 1.9% | 4.9 (-2.0) / 5.9% | 17.0 (+10.0) / 0.0% | 11.6 (+4.6) / 0.0% | 17.0 | 11.8 |

Mean absolute deviation of per-encounter mean HP lost: `sim/empirical/heuristic` 0.89 HP, `sim/empirical/random` 2.39 HP, `sim/F/heuristic` 7.79 HP, `sim/F/greedy_f` 4.30 HP.

HP ratio when entering combat (mean):

| act | human | sim/empirical/heuristic | sim/empirical/random | sim/F/heuristic | sim/F/greedy_f |
|---|---|---|---|---|---|
| OVERGROWTH | 0.649 | 0.671 | 0.597 | 0.666 | 0.639 |
| UNDERDOCKS | 0.635 | 0.669 | 0.572 | 0.658 | 0.629 |
| HIVE | 0.684 | 0.686 | 0.590 | 0.648 | 0.627 |
| GLORY | 0.832 | 0.698 | 0.608 | 0.635 | 0.629 |

## 8. Combat oracle on the actual human builds (holdout)

3583 recorded human fights from 356 held-out runs were re-scored with F on the exact pre-combat deck/relics the player had. This isolates oracle bias from deck quality: `human` is the recorded HP lost, `F` the predicted expected loss. Fights where the player used no potion are the fairest comparison with F/teacher, which never see potions.

| fights | n | human HP lost | F mean | bias (F − human) | MAE per fight | human death % | F death head % | F sampled death % |
|---|---|---|---|---|---|---|---|---|
| all | 3583 | 10.65 | 13.73 | +3.08 | 7.56 | 5.1 | 3.6 | 11.2 |
| no_potion | 2511 | 8.37 | 8.83 | +0.46 | 5.39 | 3.1 | 1.5 | 5.3 |
| potion | 1072 | 15.98 | 25.21 | +9.23 | 12.64 | 9.7 | 8.3 | 25.3 |

Per room type / act (no-potion fights):

| group | n | human HP lost | F mean | bias | MAE | human death % | F death head % |
|---|---|---|---|---|---|---|---|
| GLORY:boss | 36 | 23.36 | 45.36 | +22.00 | 24.80 | 11.1 | 31.8 |
| GLORY:elite | 52 | 12.31 | 17.74 | +5.44 | 11.02 | 0.0 | 1.3 |
| GLORY:monster | 199 | 5.60 | 5.53 | -0.07 | 5.79 | 0.5 | 0.1 |
| HIVE:boss | 41 | 26.95 | 42.94 | +15.99 | 20.10 | 19.5 | 27.3 |
| HIVE:elite | 100 | 20.20 | 22.35 | +2.15 | 10.28 | 13.0 | 4.2 |
| HIVE:monster | 487 | 6.92 | 6.57 | -0.35 | 5.10 | 2.3 | 0.2 |
| OVERGROWTH:boss | 27 | 32.44 | 35.07 | +2.62 | 11.17 | 18.5 | 7.9 |
| OVERGROWTH:elite | 100 | 18.72 | 19.80 | +1.08 | 8.12 | 7.0 | 1.8 |
| OVERGROWTH:monster | 660 | 4.54 | 3.46 | -1.08 | 3.05 | 0.9 | 0.0 |
| UNDERDOCKS:boss | 45 | 24.31 | 32.87 | +8.55 | 11.57 | 17.8 | 9.4 |
| UNDERDOCKS:elite | 111 | 16.43 | 17.06 | +0.63 | 6.30 | 9.0 | 1.2 |
| UNDERDOCKS:monster | 653 | 4.98 | 4.18 | -0.80 | 3.42 | 0.8 | 0.0 |

Encounters with the largest |bias| (no-potion fights, n ≥ 20):

| act:encounter | n | human HP lost | F mean | bias | human death % | F death head % |
|---|---|---|---|---|---|---|
| UNDERDOCKS:CULTISTS_NORMAL | 26 | 5.8 | 13.6 | +7.8 | 7.7 | 0.9 |
| HIVE:DECIMILLIPEDE_ELITE | 21 | 18.2 | 25.4 | +7.2 | 23.8 | 2.2 |
| OVERGROWTH:SLITHERING_STRANGLER_NORMAL | 20 | 7.8 | 3.2 | -4.6 | 5.0 | 0.0 |
| UNDERDOCKS:PHANTASMAL_GARDENERS_ELITE | 31 | 17.3 | 21.6 | +4.3 | 16.1 | 4.1 |
| UNDERDOCKS:LIVING_FOG_NORMAL | 28 | 9.2 | 5.2 | -4.0 | 3.6 | 0.0 |
| GLORY:SOUL_NEXUS_ELITE | 24 | 10.5 | 13.9 | +3.4 | 0.0 | 0.1 |
| OVERGROWTH:VINE_SHAMBLER_NORMAL | 24 | 8.5 | 5.3 | -3.2 | 0.0 | 0.0 |
| HIVE:HUNTER_KILLER_NORMAL | 25 | 13.3 | 10.2 | -3.1 | 0.0 | 0.1 |
| OVERGROWTH:CUBEX_CONSTRUCT_NORMAL | 21 | 7.9 | 4.8 | -3.0 | 0.0 | 0.0 |
| OVERGROWTH:PHROG_PARASITE_ELITE | 31 | 16.9 | 19.8 | +2.8 | 6.5 | 5.1 |
| HIVE:BOWLBUGS_WEAK | 52 | 5.7 | 3.2 | -2.4 | 0.0 | 0.0 |
| OVERGROWTH:BYGONE_EFFIGY_ELITE | 32 | 19.1 | 21.3 | +2.3 | 6.2 | 0.7 |
| UNDERDOCKS:PUNCH_CONSTRUCT_NORMAL | 24 | 7.7 | 5.6 | -2.1 | 0.0 | 0.0 |
| GLORY:SCROLLS_OF_BITING_WEAK | 27 | 5.2 | 3.2 | -2.0 | 0.0 | 0.0 |
| HIVE:ENTOMANCER_ELITE | 43 | 19.0 | 20.9 | +1.9 | 7.0 | 6.9 |
| UNDERDOCKS:TERROR_EEL_ELITE | 33 | 19.5 | 17.7 | -1.8 | 9.1 | 0.2 |
| UNDERDOCKS:CORPSE_SLUGS_WEAK | 102 | 5.8 | 4.1 | -1.7 | 0.0 | 0.0 |
| OVERGROWTH:INKLETS_NORMAL | 23 | 8.7 | 7.0 | -1.7 | 0.0 | 0.0 |
| OVERGROWTH:NIBBITS_WEAK | 117 | 3.0 | 1.4 | -1.6 | 0.0 | 0.0 |
| UNDERDOCKS:SEAPUNK_WEAK | 107 | 3.7 | 2.2 | -1.5 | 0.0 | 0.0 |

## 9. Known gaps in v0 (not modelled)

- Potions are ignored entirely (no potion drops, no use); the teacher and F are trained without potions as well, so the human column is the only one that benefits from potions.
- Map layout is generated STS1-style; only the visited-path type mix is checked against humans (unvisited nodes are unobservable).
- Events replay recorded human outcomes irrespective of the current state (no option choice, HP-dependent choices not conditioned, outcomes clamped so events never kill).
- Relic pickup effects only for relics whose effect shows up as HP/max HP/gold/cards deltas on ancient/treasure/combat floors; shop-only relics, card enchantments and rest-site options unlocked by relics (DIG, LIFT, COOK, …) are absent.
- Rest site heal is fixed to 30 % of max HP; SMITH upgrades only; no dual choices.
- Card rewards always offer 3 cards from the Silent pool with fitted rarity odds; no colorless/attack-only rewards, no reward-modifying relics.
- Combat: F returns an expected loss; realised loss = round(mean + pessimism·std + N(0, noise_sd)), plus a death draw from the death head. Human damage includes potions, misplays and lower-than-70 starting HP.
- Baseline policies are hand-written and do not use F; human decision quality is not reproduced (see the HP-when-entering-combat row).
