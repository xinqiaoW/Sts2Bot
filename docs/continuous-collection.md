# 持续采集与备份

执行目录为 01 的 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot`。正常采集使用真实库 `data/collection-real-runs-v4.sqlite`、普通变异库 `data/collection-mutations-v2.sqlite`、专项库 `data/collection-targeted-mutations-v1.sqlite`，采集配置为 `configs/real-runs-8s.json`。

本页说明正常持续采集。历史种子补采使用[独立工具与队列](../tools/one_off/README.md)，不会在补采结束后自动生成新构筑。

## 调度与启动

每个 worker 使用独立 Wine 环境，按真实、真实、普通变异、专项变异循环领取任务，空队列允许借用。两个变异队列各低于 600 个 pending 时补充构筑，不要求真实队列为空。worker 数量由 `--runtimes` 列表决定；两种采集并行时，runtime 的 Wine prefix 和 `data_dir` 必须互不重叠。详见[来源与调度](source-versions-and-scheduling.md)、[变异规则](mutations-8s.md)。

控制器、采集池和各 worker 分别持有独占锁。启动前核对 `data/collection-session.json`、`data/active-collection.json`、实际进程和锁，确认库、配置与 runtime 对应同一套已部署环境。会话文件中的旧 PID 和 worker 数量不能单独证明进程正在运行。人工暂停或故障原因尚未处理时，不应清除停止标记或直接重启。

下面读取会话配置启动正常控制器；需要先确认该配置是本次要运行的配置，且没有另一个控制器。代码不会清除暂停标记：

```bash
cd /data1/pl/ImageTask/wxq/Projects/Sts2Bot
.venv/bin/python - <<'PY'
import json, subprocess, sys
from pathlib import Path
s = json.loads(Path('data/collection-session.json').read_text())
assert Path.cwd() == Path(s['project'])
assert s['collect_only'] and s['stop_at'] is None
assert s.get('state') not in ('paused', 'failed')
assert not s.get('resume_requires_explicit_user_request', False)
assert not Path(s['active_db']).with_suffix('.continuous.stop').exists()
subprocess.run([
    sys.executable, '-u', '-m', 'tools.collect_continuous',
    '--db', s['active_db'], '--config', s['config'],
    '--runtimes', *s['runtimes'],
    '--reserve-gib', str(s['reserve_gib']),
    '--worker-start-gib', str(s['worker_start_gib']),
    '--mutation-workers', str(s['mutation_workers']),
    '--mutation-db', s['mutation_db'], '--mutation-policy', s['mutation_policy'],
    '--targeted-db', s['targeted_db'], '--targeted-policy', s['targeted_policy'],
    '--source-dir', 'data/external/spire-codex',
    '--source-start', s['historical_source_start'],
    '--backfill-dir', s['backfill_dir'], '--collect-only',
], check=True)
PY
```

`--reserve-gib` 是运行内存预留，设为 0 时关闭基于该预留的排空；`--worker-start-gib` 是新 worker 的启动预算，两者不等于进程实际内存上限。参数应结合共享主机和用户 cgroup 限额设置。`--collect-only` 不训练、不覆盖 `checkpoints/v1`；不传 `--stop-at` 时没有固定截止时间。

## 来源补充与种子

`encounter_seed_policy` 引用同目录 `mutations-targeted-8s.json` 的 43 个编组，每个新构筑–编组安排 24 个种子，其余编组 4 个。真实导入、普通变异和专项变异共用该规则；前 4 个种子及任务 ID 保持兼容。配置在进程启动时加载，修改配置不会自动重扫来源或扩充已排队任务。

正常持续采集按构筑 ID 去重：真实导入检查三个正常活动库，重复构筑不再添加编组或种子任务；真实库中的重复构筑仍保留来源记录以便追溯。两个变异生成器也做跨库构筑去重。历史旧构筑的额外种子由独立补采工具负责。

真实 pending 少于 12,000 时允许拉取下一页，单页导入可使队列暂时超过水位。新上传来源和历史来源回补共用至少 31 秒的请求间隔与失败退避；完整处理一页才推进游标。`compatible-archive-v1` 使用独立游标扫描兼容旧版本。来源等待不会阻止已有任务和变异采集。

## 故障与停止

原生失败保留请求、日志和全部 attempts，按 `retry_then_quarantine_v1` 每任务最多 3 次尝试；仍失败则写入 `job_quarantines` 并隔离该任务，其他任务继续。失败或超时即使带完整 observation 也不能充当标签。无效 observation、配置或来源错误须诊断，不能批量隔离掩盖。一个 worker 连续隔离 3 个不同任务且其间没有成功时，触发系统性问题处理。

已完成、已隔离任务不自动重打，不清零 attempts，不伪造 lease。有效租约不能强行抢占；确认过期无主的任务按现有 claim 路径恢复。

停止正常采集：

1. 创建主库对应的 `.continuous.stop`，并向已核实的控制器发送 SIGTERM，等待其退出，防止继续补充来源或拉起采集池。
2. 在本池每个 runtime 的 `data_dir` 写入 `collector.stop`，让在途战斗完成，池也会停止续接 worker。向池发送 SIGINT/SIGTERM 同样会触发其排空流程；必须先核实进程属于本次采集。
3. 核对 worker 退出、running=0，再做最终一致性备份。人工中断池可能在状态文件中记为 `failed`，应结合退出原因判断，不能据此重置任务。

恢复时先处理停止原因，核对会话配置与锁，再更新暂停状态和相应停止标记。若同时运行历史补采，应按其 README 单独停止或恢复，不能混用两套池的进程信息。

## 备份

`tools.local_backup` 对单库维护两个轮换槽，目录和状态文件由 `--directory`、`--state` 指定；默认每轮完成后等待 300 秒。实际部署也可由 `tools.one_off.backfill_backup` 串行备份多个库，它默认每轮后等待 3,600 秒，通过重复的 `--additional-db` 纳入正常采集库。备份位置和周期以进程参数及备份状态为准。

先保存 session、配置、来源游标和历史 plan，再固定 WAL 读取快照并用 SQLite backup API 导出；不能直接复制活跃数据库或 WAL。`source-backfill/` 包括历史来源游标。恢复较早游标可以幂等重放来源，不能手工跳过未导入页。

核对成功状态、备份摘要、SQLite quick_check 和任务计数。有 I/O 等待但仍在推进时不要中断快照。恢复点间隔包含等待时间和整轮备份耗时；同盘双槽备份不能替代异机容灾。

## 日常检查

读取主库旁的 `.parallel.json`、`.continuous.json`、各库备份状态，以及实际进程和锁；判断产出看近期 complete 增量和有效原生结果。控制器导入来源或启动时校验数据库可能暂不刷新状态，应结合 CPU、I/O、日志和进程身份判断，不能仅凭状态文件年龄重启。

数据验收和已知限制见[验证与审计](validation.md)。
