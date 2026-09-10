# 切回 01 继续真实构筑采集

**最新状态（2026-09-07 晚）：用户要求提高搜索时间并恢复采集、监督，覆盖下方暂停记录。** [8 秒搜索批次](search-8s.md) 已通过四个区域的原生验收，恢复 25 路采集、每 10 分钟巡检及每 300 秒备份。新活动批次为 v3 / `configs/real-runs-8s.json` / Medium、short_only、8000ms、DOP1；旧 v2 数据和失败证据全部保留。后续运行与恢复必须以 session.active_db、session.config、session.teacher 为准，不得执行历史 v2 恢复脚本。实际阶段看 `data/return-to-01.json`；若后续为 `pilot`，只检查现有 driver，禁止启动第二套。

**暂停历史（2026-09-07 13:33，北京时间；已由晚间明确恢复指令覆盖）：** 当时采集、新来源和历史下载、自动重试、自动巡检均暂停，最后备份保存；72,959 场成功结果、21,766 场待采、2 场失败及完整游标和 attempts 保留，29 个服务/worker 锁空闲。证据见 `evidence/user-pause-20260907/verification.json`，不得重放该目录暂停脚本。

用户于2026-09-07明确要求改用01继续采集，覆盖旧租用机主机指示。迁移与验收状态以01项目中的 `data/return-to-01.json` 为准；迁移期间不重复启动服务。

- 主机：SSH别名 `01`，项目 `/data2/pl/ImageTask/wxq/Projects/Sts2Bot`。
- Python：`.venv/bin/python`，指向既有py311环境；不训练、不覆盖 `checkpoints/v1`。
- 活动库：`data/collection-real-runs-v2.sqlite`。由2026-09-07 04:49:34北京时间的租用回传备份通过SQLite backup API恢复，基线66,123成功、20,581范围外旧任务。备份及01旧数据库保留，旧随机队列不领取。
- 当前配置：`data/collection-session.json`、`data/active-collection.json`。旧 `rental-session.json`、`rental-handoff.json` 和旧 `resource-profile.json` 属于迁移历史，不按旧PID恢复服务。
- 并发：26个独立Wine worker；01是共享主机，预留32 GiB、每worker启动预算2 GiB；完整启动门槛84 GiB。原生老师仍Medium、short_only、2000ms、dop1、120秒。
- 游戏后台线程：`.runtime/game-windows/override.cfg` 为 `[threading]` 下 `worker_pool/max_threads=8`，不能丢失这个部署文件。Godot默认使用所有逻辑CPU，01有256个逻辑CPU，未经限制的每游戏进程实测287–289条线程，26路并发触及用户cgroup的8192线程上限，四场尚未进入原生请求即启动失败。该用户作用域的失败计数与日志已归档；只限制本项目游戏的辅助线程，不更改账号限制、其他任务或求解器DOP。配置路径、摘要与硬件批次记录在session的runtime_environment。官方说明：[Godot ProjectSettings](https://docs.godotengine.org/en/4.6/classes/class_projectsettings.html)。
- 来源：从备份的第80页游标接续，保留31秒请求间隔、窗口结束300秒等待及429退避；不手改游标跳过未验证数据。原始来源与构筑来源全部保留。
- 备份：`tools.local_backup`每300秒将一致快照写入 `backups/01-active/slot-a`、`slot-b` 交替两个槽。`data/local-backup.json` 指向最新成功槽和摘要，失败保留 `last_success`。租用回传备份目录不被这些快照覆盖。
- 并发备份使用 `pinned_wal_read_v1`：WAL活动库先建立只读事务并固定读取快照，再增量backup，避免采集持续提交让备份反复重启。WAL写入仍可继续；快照完成即关闭只读连接释放快照。共享snapshot函数已加入此处理，非WAL库保留原行为。旧备份进程曾超过十分钟无法产出新快照；受控替换该进程，未重启采集器。并发提交回归测试在旧代码失败、修复后通过，备份/控制器定向31项通过；依据 [SQLite在线备份说明](https://sqlite.org/backup.html)。
- 持续运行直到用户要求停止。空队列时池正常退出、控制器 `waiting_source` 属于正常；新来源到达后自动开池。实际PID读最新parallel/continuous文件，不能因session里历史pool_pid退出而误判。
- 自动巡检转向01，停止对租用机的自动恢复；租用机持续不可达，无法确认它的实际进程或是否有未回传结果，不自动释放实例或变更计费。以后如果取到额外旧结果，应先逐任务核对来源与标签，不能覆盖01新结果。

输入、怪物窗口和原生验收规则继续遵守 `docs/spire-codex-run-assessment.md`、`docs/unadapted-relics-20260906.md`：Silent/A10/70满血/无药水、保留升级和逐张附魔、合法可复现遗物计数、source_floor_window_v1前后各2层且不跨幕，每目标4种子。老师source7ba49f9/protocol2、输入relic_pickup_normalization_v4、身份spire_codex_metadata_v2、HP规则native_max_hp_costs_v2保持。

2026-09-07启用历史补采：控制器额外传入 `--backfill-dir data/external/spire-codex-history`，先补最近缺失一周，再扫无日期过滤的完整公开存档，与现有新来源共用31秒请求预算。恢复时不得漏掉该参数或重置任何来源游标，具体阶段、去重与备份位置见 [持续采集](continuous-collection.md)。备份新增 `source-backfill/` 元数据，全部来源游标在数据库快照之前捕获，避免恢复时跳过快照以后的导入。

失败先保留证据，按用户持续恢复授权独立重试，不清零attempts、不重做complete、不放宽原生Passed或实际输入核验。旧一次性恢复脚本都属于已经完成的历史操作，不能再次执行。任务恢复后核对新原生产出、锁、资源和新备份；正常巡检保持安静。

本次源码、旧代码压缩包、数据库逐表摘要、原生验收及启动结果放在 `evidence/return-to-01-20260907/`。

部署检查共152项通过。01旧目录缺少逐张附魔目录数据，已显式同步包含24种附魔的 `catalogs/game-0.111.0.raw.json`；该文件被Git忽略，后续部署必须显式核对，不能只打包 `git ls-files`。迁移首批三个全新任务分别覆盖暗港、巢穴和密林，原生Passed且完整实际构筑核对通过。固定2000ms搜索受机器与调度影响，旧新机器结果带collector.host，迁移记录单独保留，不把环境验收说成标签逐值等价证明。

线程限制后的四场独立重试全部原生Passed，最大进程线程数44–46，原四条失败attempts保留。随后26个worker全部有新成功产出，29把锁齐全，账号线程约3100，启动故障没有复现。复核原备份的66,123条成功jobs、66,341条attempts、2,912条builds全部列值原样保留，见final-preservation.json。最新进度、资源与备份以verification.json及线上状态为准，不把验收数字当停止配额。

2026-09-07 10:07巡检：空队列后来自动补入80场并重开采集池，77场完成、三场首请求超时后有界停止。已按持续授权各独立复验一次，三场全部原生Passed、原失败attempts保留，未更改老师或期限。恢复后的池/控制器、来源和新备份见 `evidence/heartbeat-timeouts-20260907-1007/verification.json`；该目录的一次性恢复脚本不得重放。此时总计68,719场，暂时无待采时继续等待新来源。

2026-09-07 12:10巡检：历史补采中一场GLOBE_HEAD_NORMAL在第8回合触发BeamRetentionPolicy.RankFinal重复SearchNode键异常，随后达到120秒期限；这属于求解器异常，不能归为内存或通用基础设施故障。相同输入、目标、种子和老师独立复验一次后原生Passed，第11回合掉血70，旧失败attempt保留。已恢复26路采集和带 `--backfill-dir` 的控制器，继续历史与新来源；未更改老师、超时或错误分类。证据见 `evidence/globe-head-timeout-20260907-1210/`，该目录恢复脚本已执行，禁止重放。

2026-09-07 13:05巡检：六场QUEEN_BOSS因求解器路线回放校验异常而超时，各独立重试一次，四场Passed、两场仍在第1回合复现HP回放不一致；现72,959成功、21,766待采、2失败、无running。未放宽老师或校验。两个剩余任务前缀2df62ebb、f125e102，均attempts=2；下轮按持续授权各至多追加一次，保留已有尝试，不能重试四场complete或重放本轮脚本。采集池和控制器暂受既有失败保护阻挡，备份及巡检保持运行。完整ID、输入和原生诊断见 `evidence/queen-timeouts-20260907-1305/README.md`。
