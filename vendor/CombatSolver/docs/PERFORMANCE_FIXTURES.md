# 搜索性能回归样例

仓库只提交可审计的最小化 gameplay fixture。原始问题包、完整日志、截图、Profiler 和存档均留在 Git 忽略目录，不属于公开测试数据。

两个样例都能脱离原始问题包运行，但它们属于合成战斗根或战前状态重建，不是原生战斗状态回放。headless 数字用于比较固定工作量、累计分配和 GC 行为，不能替代正常可见 Steam 会话的帧时间结论。

完整策略测试必须逐值遵守样例设置。固定节点或 5 秒短搜只作为显式诊断变体，不能冒充完整策略结果，也不能用于降低路线质量。

## Silent 大牌组 Fork/选牌压力

- fixture：`coverage/unattended/search-performance-silent-large-deck-cards.json`
- 输入：`44` 条聚合记录，共 `396` 张牌（手牌 `7`、抽牌堆 `389`）。
- 白名单：仅 `cardId / pile / count / upgradeLevels / treatAsDeckCard`。
- 排除：存档、RNG、遗物、药水、Power、日志、路径、平台和环境信息。

```bash
./tools/run-unattended-test.sh \
  --scenario-id SEARCH-PERF-SILENT-LARGE-DECK-5S \
  --character-id SILENT \
  --seed SEARCH_PERF_SILENT_LARGE_DECK \
  --encounter-id AEONGLASS_BOSS \
  --ascension 5 \
  --act-index-for-test 2 \
  --enemy-current-hp 512 \
  --initial-enemy-move-ids-json '["EBB_MOVE"]' \
  --initial-player-hp 65 \
  --initial-player-max-hp 65 \
  --initial-player-energy 3 \
  --clear-player-piles \
  --cards-path coverage/unattended/search-performance-silent-large-deck-cards.json \
  --performance-preset-for-test VeryHigh \
  --potion-policy-for-test Smart \
  --search-max-degree-of-parallelism-for-test 8 \
  --force-short-search-only \
  --short-search-budget-override-milliseconds 5000 \
  --measure-search-phases \
  --expected-initial-search-phase Short \
  --expected-initial-deep-search-triggered 0 \
  --expected-initial-executable-action-count-at-least 1 \
  --stop-after-initial-solver-result-assertion \
  --timeout-seconds 120 \
  --exit-on-complete
```

Runner 同时断言 VeryHigh 的 Beam `36/90`、节点 `10000/50000`、出牌分支 `30/48` 和 No-GC `16,000,000,000 B` 均保持原设置。

## Necrobinder 药水/高分支压力

- fixture：`coverage/unattended/search-performance-necrobinder-potion-heavy-run-snapshot.json`
- 输入：`38` 张战前牌、`20` 件遗物、`2` 瓶药和生命/药水槽；战斗初始化后形成 `41` 张搜索根。
- 白名单：顶层仅 `players`；玩家只保留 runner 支持的 `deck / relics / potions / max_potion_slot_count / max_hp / current_hp` 及合法子字段。RNG 由下方公开合成 seed 生成。
- 排除：地图、房间历史、时间、平台、账户、日志、路径和环境信息。
- 边界：这是战前白名单投影，不能作为原生战斗逐动作 replay。

```bash
./tools/run-unattended-test.sh \
  --scenario-id SEARCH-PERF-NECROBINDER-POTION-QUICK \
  --character-id NECROBINDER \
  --seed SEARCH_PERF_NECROBINDER_POTION \
  --run-snapshot-path coverage/unattended/search-performance-necrobinder-potion-heavy-run-snapshot.json \
  --encounter-id AEONGLASS_BOSS \
  --ascension 10 \
  --act-index-for-test 2 \
  --enemy-current-hp 526 \
  --initial-player-hp 41 \
  --cards-json '[]' \
  --search-max-degree-of-parallelism-for-test 8 \
  --performance-preset-for-test VeryHigh \
  --potion-policy-for-test RequireAtLeastOne \
  --force-short-search-only \
  --short-search-budget-override-milliseconds 5000 \
  --measure-search-phases \
  --expected-initial-search-phase Short \
  --expected-initial-deep-search-triggered 0 \
  --expected-initial-executable-action-count-at-least 1 \
  --stop-after-initial-solver-result-assertion \
  --timeout-seconds 120 \
  --exit-on-complete
```

Runner 同时断言 VeryHigh 原 Beam、节点、分支、药水策略与精确 `16 GB` No-GC 契约，并要求返回可执行且使用药水的候选。

Windows 与 Linux 的单行等价命令登记在 `docs/TEST_MATRIX.md`。

## 性能解释边界

- v0.21.3 固定 `576` 展开的历史 A/B 中，两侧均为 `3463` 次转移、`1124` 个选牌分支，并返回相同 3 回合、预计掉血 `2` 的路线。上游为 `5116.3 ms / 1,039,502,640 B`，优化版本为 `3985.0 ms / 528,876,328 B`：累计分配降低 `49.12%`，单次 headless 墙钟缩短 `22.11%`。
- 精确 `16 GB` No-GC 的完整长搜保持 `7018/52644/23196` 工作量、评分、10 回合胜利、玩家/敌人 HP `9/0`、预计战损 `56`、卖血 `11` 与两瓶药使用结果不变；连续三个优化版本约为 `52.6–53.6 s / 11.646–11.655 GB`，差异属于单次 headless 波动。
- 以上结果没有改变 Beam、节点、时间、分支、评分、RNG、候选顺序或药水政策，也不构成可见 Steam 帧率结论。
