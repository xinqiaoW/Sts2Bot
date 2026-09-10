# 2026-09-05 必备工具超时与恢复

旧版采集在北京时间 21:37 停止，`data/collection.sqlite` 保存 918 场完成、8 场失败、5154 场待采集。8 个失败都是同一个带 `TOOLS_OF_THE_TRADE`、`LAVA_ROCK` 的静默卡组：骇鳗 4 场、灵魂异鱼 2 场、瀑布巨人 2 场。超时前处于第 14–17 回合，旧数据和尝试记录完整保留，不能把这些失败当作死亡或掉血标签。

根因在 CombatSolver 的运行时衔接：最后一个已搜索 `EndTurn` 带有下一回合弃牌选择，但 `TryGetPlannedTurnSetupChoices` 额外要求下一回合还有可执行 continuation。到达搜索末尾时没有 continuation，原生选牌页面无人接管。修复提交 `33babbe` 允许先重放已有选择，再进入 Play 交由原有重新搜索逻辑处理。配套 UI snapshot 支持仅有开始选择的末尾边界，明确显示后续需计算。没有调整人工分数、搜索预算、战斗规则或失败标签。

最终边界观察 `horizon-fixed-boundary-20260905` 在第 6 回合依次记录原生弃牌、计划选择重放、`SEARCH_REUSE_MISS reason=continuation_missing`。观察完成后停止专用游戏进程，没有将它记为完整战斗 Passed 或训练数据。证据见 `evidence/horizon-fixed-boundary.json`。第一次中间修复暴露 UI 的相同假设并超时，最终版本已包含配套修复；没有延长 120 秒超时。Release 构建 0 警告/错误，结构门禁通过。

DLL 变化后，仍遵守每个数据库使用同一老师的规则：旧库冻结，新库 `data/collection-horizon.sqlite` 使用相同 72 个卡组、目标和随机种子重新安排 6080 场，优先重跑原来失败的 8 场。`configs/teacher-56bc61c.json` 保留旧老师，`configs/teacher.json` 指向修复后的 DLL。任务 ID 包含老师信息，两库任务 ID 不重合；新旧标签不悄悄混合。建库时核对了全量卡组/目标/种子集合相等，见 `evidence/horizon-recollection.json`。

当前活动库路径保存在 `data/active-collection.json`；池状态查看 `data/collection-horizon.parallel.json`，日志 `logs/parallel-horizon.log`。8 个独立 worker 和 32 GiB 内存保留量继续使用。完成全部任务且没有失败后，池才启动 CPU 基线训练。旧库的完成数不能当作新库的训练进度。

恢复后的原 8 个失败场次已全部获得原生 `Passed` 和 `trainingObservation.complete=true`。三组怪物均真实击败玩家，净掉血 70，终局在第 11–25 回合，用时 56.8–71.4 秒（包含首次启动）。这些是有效负样本，不是超时转换。完整 runId 与开战/终局观察保存在 `evidence/horizon-regression.json`。随后一分钟完成约 45 场，可用内存约 53 GiB；这仍是短窗口速度，不能保证所有后续卡组的吞吐。

随后在新库完成 123 场时，一例 `FOGMOG_NORMAL` 在复用进程第 4 场触发原生 `MaxEnumValueCache.Get` 字典并发损坏，原有“只检测进程首场”的恢复范围未覆盖，故再次停止。已将同一窄错误签名的检测扩展到每个请求，仅扫描该请求新增日志，继续保留最多 3 次尝试上限。已有失败记录保留，诊断确认后单独重排这一个任务；其他超时仍停止。该变更只在 Python 采集器，老师 DLL 不变，新库的 123 场无需重采。

????????? 5 ?????????????????????????????????? 3 ??????/???????????????
