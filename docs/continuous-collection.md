# 持续采集与备份

工作目录：01 的 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot`。当前真实库为 `data/collection-real-runs-v4.sqlite`，变异库为 `data/collection-mutations-v2.sqlite`，配置为 `configs/real-runs-8s.json`。实际运行以 session/active、进程命令行和锁为准，不依赖文档中的历史 PID。

## 调度与启动

25 个 worker 共用一个池，每个使用独立 Wine 环境。20 个优先领取真实任务，5 个优先领取变异任务；偏好的队列无可领取任务时借用另一队列。变异低于 600 个 pending 时按策略补充，不再要求真实队列为空。详见[来源与调度](source-versions-and-scheduling.md)、[变异规则](mutations-8s.md)。

控制器独占 continuous 锁，可接管已存在的正常池；池和每个 worker 也有独占锁。以下是**已部署生产副本**的恢复示例，使用前先确认没有另一个控制器；不可在旧 Git 副本直接套用：

```bash
cd /data1/pl/ImageTask/wxq/Projects/Sts2Bot
.venv/bin/python - <<'PY'
import json, subprocess, sys
from pathlib import Path
s = json.loads(Path('data/collection-session.json').read_text())
assert Path.cwd() == Path(s['project'])
assert s['collect_only'] and s['stop_at'] is None
subprocess.run([
    sys.executable, '-u', '-m', 'tools.collect_continuous',
    '--db', s['active_db'], '--config', s['config'],
    '--runtimes', *s['runtimes'],
    '--reserve-gib', str(s['reserve_gib']),
    '--worker-start-gib', str(s['worker_start_gib']),
    '--mutation-workers', str(s['mutation_workers']),
    '--mutation-db', s['mutation_db'], '--mutation-policy', s['mutation_policy'],
    '--source-dir', 'data/external/spire-codex',
    '--source-start', s['historical_source_start'],
    '--backfill-dir', s['backfill_dir'], '--collect-only',
], check=True)
PY
```

运行内存预留为 0；新进程仍按每 worker 2 GiB 估算启动条件。控制器不设截止时间，不训练、不覆盖 `checkpoints/v1`。不能改用 CLI 的 v2 / 2 秒默认参数，也不能领取已封存旧库的 pending。

## 来源补充

真实 pending 少于 12,000 时允许拉取下一页，单页导入可使队列暂时超过水位。新上传来源和历史回补共用至少 31 秒的请求间隔与失败退避；完整处理一页才推进游标。当前旧版回补使用 `compatible-archive-v1` 独立游标，不重置已完成的旧历史扫描。实时来源等待或历史扫描暂缓不会阻止已有任务和变异采集。

## 故障与停止

原生失败保留请求、日志和全部 attempts，按 `retry_then_quarantine_v1` 每任务最多 3 次尝试；仍失败则原子写入 `job_quarantines` 并隔离该任务，其他任务继续。失败或超时即使带完整 observation 也不能充当标签；明确的清理期限异常只进入重试路径。无效 observation、配置或来源错误须诊断，不能批量隔离掩盖。一个 worker 连续隔离 3 个不同任务且其间没有成功时，触发系统性问题处理。

已完成、已隔离任务不自动重打，不清零 attempts，不伪造 lease。有效租约不能强行抢占；确认过期无主的任务按现有 claim 路径恢复。故障诊断不要终止其他用户任务或修改共享系统限制。

用户要求停止时：先停止已核实的控制器，再在每个 runtime 的 `data_dir` 写入 `collector.stop`，让在途战斗完成；核对 worker 退出和 running=0 后做最终一致性备份。不要通过中断池来代替这一收尾流程。

## 两路备份

| 数据 | 双槽目录 | 状态 |
| --- | --- | --- |
| 真实 v4 | `backups/01-active-card-state/slot-a`、`slot-b` | `data/local-backup.json` |
| 变异 v2 | `backups/01-mutations-card-state/slot-a`、`slot-b` | `data/mutation-backup.json` |

`tools.local_backup` 每 300 秒发起下一轮，完成时间还包含备份耗时。先保存 session、配置、来源游标和历史 plan，再固定 WAL 读取快照并用 SQLite backup API 导出；不能直接复制活跃数据库或 WAL。`source-backfill/` 包括 `compatible-archive-v1/cursor.json`。恢复较早游标可以幂等重放来源，不能手工跳过未导入页。

核对成功状态、备份摘要、SQLite quick_check 和任务计数。有 I/O 等待但仍在推进时不要杀掉备份。备份和采集位于同一磁盘，不能把双槽轮换当成异机容灾。

## 日常检查

读取 `data/collection-real-runs-v4.parallel.json`、`.continuous.json`、两路备份状态和实际进程/锁；判断产出要看近期 complete 增量与有效原生结果。控制器批量导入来源时可能暂不刷新状态，需要检查实际 CPU/I/O 进展，不能仅凭状态年龄重启。

自动巡检频率以本机应用保存的自动化配置为准，不在文档中硬编码另一套周期。正常运行保持安静，新的实质故障和恢复完成才通知。现行生产检查脚本与历史审计边界见[验证与审计](validation.md)。
