# 8 秒搜索批次

**2026-09-08 战后清理超时修复：** Failed / cleanup 的原生期限异常可能同时带有 complete observation，原重试入口拒绝此组合而导致全池退出。现在仅允许明确的 System.TimeoutException / EnsureWithinDeadline 清理异常进入既定最多三次重试，原 Failed 结果及 observation 原样保留，不能用作标签；其他完整 observation 异常与成功验收规则不变。见 [恢复证据](../evidence/cleanup-deadline-20260908/README.md)。该目录 deploy.py 是一次性脚本，禁止重放；files.json 覆盖旧部署清单中同名文件的历史摘要。

**2026-09-08 最新内存授权：** 用户要求取消内存预留线、只要还能运行就持续采集。当前 pool/controller/session/active 的 `reserve_gib=0`，覆盖本文及历史文档所有 32 GiB 预留和 82 GiB 启动要求。运行中的 worker 不因可用内存降到某条线而统一收尾；新启动仍估算每 worker 2 GiB（25 个全新 worker 合计 50 GiB，运行后不保留这部分）。保持 25 worker、8 秒搜索及故障重试/隔离、备份和巡检，不干预其他账号或系统限额。巡检从 session 动态读取预留值，不能恢复旧阈值。部署记录见 [取消预留线](../evidence/no-memory-reserve-20260908/README.md)，deploy.py 为一次性脚本，禁止重放。

**2026-09-08 夜间持续采集规则（覆盖下文旧的单场失败全局等待规则）：** 用户明确要求出现问题自主处理，夜间持续采集，不等待回复。当前 8 秒配置新增 `native_failure_policy=retry_then_quarantine_v1`：原生异常保存证据后重启该游戏进程，每任务最多三次尝试，仍失败则原子地保留最终 failed attempt 和隔离审计并将任务置为 quarantined，其他 worker 继续工作。Passed 的完整输入/生命验收不变；InvalidObservation、配置和来源问题仍需诊断，不能批量掩盖。连续三个不同任务隔离且其间没有成功会触发系统性问题诊断，由巡检自主修复恢复。动态隔离清单以数据库 `job_quarantines` 为准，session 中 ID 列表为同步时快照，不能硬编码隔离数量。现有两场女王任务 `74c0f9cf...`、`d184a2ed...` 已各独立复验失败，连同以前两场单独隔离，保留全部尝试；其他女王战斗仍照常采集。部署与证据见 [夜间持续采集](../evidence/overnight-resilience-20260908/README.md)，其中 deploy.py 为已执行的一次性脚本，禁止重放。25 worker、8 秒老师、32 GiB 预留、300 秒备份、10 分钟巡检和直到用户叫停均保持。

2026-09-07 22 时用户批准隔离反复失败任务并继续其他采集。任务 `89fcab7cbeb604dda3473737b7f0ea73d03cb9f559877d559e645196269dc125`（无厌沙虫）九次尝试后改为 `quarantined`；错误、输入、结果和全部 attempts 原样保存，`job_quarantines` 记录原始行、原因和审计摘要。它没有有效标签，不再自动重试，不因重新导入来源恢复，也不阻塞池或来源控制器。隔离按任务进行，其他无厌沙虫任务照常采集；新增未知失败仍须诊断。该规则覆盖旧巡检中对此任务的重复重试要求。证据见 [隔离与恢复](../evidence/quarantine-20260907-2211/README.md)，该目录 deploy.py 是一次性脚本，禁止重放。巡检应分别报告 complete、pending/running、failed 和 quarantined，并核验隔离审计及原始尝试未变；不得把隔离计入成功或擅自解除隔离。

此次恢复验收期间另一场 `7727e9e11dc50a5534b292e32d33eac07de5fbffa6200ea7ddc8de11c1623983`（SLIMES_WEAK）出现原生动画访问冲突，独立复验又出现 NativeEnumCacheFailure；原分类及两次尝试均保留，亦单独隔离后恢复其他采集。当前隔离清单以 session.quarantined_job_ids 和 job_quarantines 为准，共两场；不自动重试这两场，不因隔离数量不变重复通知。retry_process_exit.py 和 quarantine_native_crash.py 都已执行，禁止重放。此处理未修复原生求解器内部错误，也不放宽新故障检查。

2026-09-07 用户明确要求保持采集方法，提高搜索深度或时间，并恢复持续采集、监督。短搜由 2000ms 调整为 8000ms，其余老师参数保持 Medium / short_only / DOP1 / 120 秒整场期限；仍 Instant、动作延迟零、NoGC 关闭。时间是每次搜索的软预算，节点和分支上限不变，不保证每场都搜索满 8 秒或都优于旧结果。

- 活动库：`data/collection-real-runs-v3.sqlite`。
- 配置：`configs/real-runs-8s.json`。旧 `configs/real-runs.json` 仍代表 2 秒，不可用于新队列。
- 老师 DLL：原 7ba49f9 / protocol2，未替换；teacher.search_ms 变为 8000。完整老师以 session.teacher 为准。
- 老数据库 `data/collection-real-runs-v2.sqlite` 保留 72,959 complete、21,766 pending、2 failed、20,577 excluded_target 以及所有 attempts。它是历史批次，不能再领取或给旧结果改老师。
- 新库复制原始来源、构筑和来源窗口，将原 21,766 pending 生成新老师任务 ID，保存 `teacher_batch_origins` 到原任务的映射。旧完成任务不批量重做。两场旧女王失败及其原始尝试留在原库供诊断，没有成为有效标签，也没有计入新批次的成功或失败。
- 原 source_runs/report 等来源审计记录保留原内容，其旧 scheduled_now 仍是旧批次历史报告，不代表新库产出。新任务和新标签只含 8 秒 teacher；重叠来源由原导入身份继续去重。
- 实时及历史游标原样接续，`--backfill-dir data/external/spire-codex-history` 保留；仍只取同一 .run、同幕 f±2 实际怪物编组、每目标四种子。
- 新轮换备份为 `backups/01-active-8s/slot-a,b`，`data/local-backup.json` 指向活动批次。旧 `backups/01-active/` 两个槽保留。备份捕获 session.config 指向的 8 秒配置，继续使用固定 WAL 快照及先读来源游标规则。
- 01 继续保留 32 GiB 内存。首次启动按当时可用内存减去保留和 4 GiB 余量确定 worker 数，上限为原 26；实际数量及运行时列表读 session，不用旧历史 PID。
- 不训练、不覆盖 checkpoints/v1，不更改游戏本地 Mod；不设五点或五小时截止。原失败保护、完整实际输入核验和自动诊断后有界重试规则保持。

验收及启动入口 `evidence/search-8s-20260907/resume.py` 是一次性脚本，不可重放。准备、原生验收、启动状态分别保存在同目录；`data/return-to-01.json` 为 pilot 时，只核对 driver 和日志。验收失败先保留 attempts，再依据当前 8 秒配置诊断，禁止降低预算、清空失败或恢复旧 2 秒标签。

常规恢复必须同时使用 session 中的新 db、config、runtimes、reserve_gib、worker_start_gib，控制器带 `--collect-only --backfill-dir`；备份启动显式指定新 db 和新 directory。旧库与旧控制器的 stop 标记保留，新批次停止标记只有用户明确恢复时才清除。只读监控脚本已改为从 session 动态选择活动库和搜索配置。

核验：队列迁移 4 项测试通过（源库逐字节不变、新任务身份、旧标签/失败保留、拒绝活动租约/越界任务/其他老师改动），01 上迁移与备份共 8 项通过；另增加并通过活动配置备份检查，确认备份包含 8000ms 配置且配置缺失时拒绝备份。

四个 act_id 的 8 秒原生验收全部 Passed，掉血分别 2、0、3、4，实际卡牌、附魔、遗物计数和终局生命由原 Store.finish 完整验收。正式启动为 25 worker（启动时资源预算所得），pool PID 1786596、controller PID 1786620、backup PID 1786621，历史补采参数保持；这些仅是首次启动记录，后续 PID 看最新状态文件。验收证据为 `evidence/search-8s-20260907/native-acceptance.json` 和 `native-attempts.json`，不据此宣称所有构筑标签质量都提高。
