# 持续采集真实构筑

2026-09-11：活动真实库为 `collection-real-runs-v4.sqlite`，变异库为 `collection-mutations-v2.sqlite`；备份位置分别为 `backups/01-active-card-state` 和 `backups/01-mutations-card-state`，保留旧批次备份。25 路、8 秒、预留 0、无截止时间、每 30 分钟巡检保持。历史 v3/v1 pending 只作为迁移来源记录保留，不能再次领取。见 [卡牌状态适配](card-state.md)。

本机 01：`/data2/pl/ImageTask/wxq/Projects/Sts2Bot`。活动库、配置、runtime 列表、worker 数、`reserve_gib` 和老师以 `data/collection-session.json`、`data/active-collection.json` 为准。当前是 8 秒批次，详见 [8 秒搜索](search-8s.md)；切回本机时的环境见 [切回01](return-to-01.md)。旧随机库和 v2 / 2 秒库保留，不再领取。采集直到用户要求停止。验收或恢复期间不要另起一套控制器。

```bash
# 参数必须从 session 读取，不要套用历史 v2 / 2 秒 / 32 GiB 命令。
# 现行为 --db data/collection-real-runs-v3.sqlite --config configs/real-runs-8s.json
# --runtimes 为 session.runtimes（现 25 路），--reserve-gib 现为 0，--worker-start-gib 2。
.venv/bin/python -u -m tools.collect_continuous \
  --db <session.active_db> --config <session.config> \
  --runtimes <session.runtimes...> \
  --reserve-gib <session.reserve_gib> --worker-start-gib <session.worker_start_gib> \
  --collect-only \
  --backfill-dir data/external/spire-codex-history
```

控制器独占 continuous.lock，接管已有 pool.lock，核实 worker 锁后才启动新池。每个 worker 使用独立 Wine prefix。`--collect-only` 只记完整面板已采集，不覆盖 `checkpoints/v1`，也不会反复训练或调用旧 evolve。

原生失败保留完整 attempts。当前 8 秒配置启用 `retry_then_quarantine_v1`（`max_attempts=3`，证据目录 `evidence/native-failures-v3`；与 session、`configs/real-runs-8s.json` 一致，详见 [8 秒搜索](search-8s.md)）。覆盖 `Failed`、`Timeout`、`ProcessExited` 以及已命名的原生故障分类：先保存本次请求的新日志，停掉该游戏进程再独立重试；同一任务三次仍失败则原子写入 `job_quarantines` 并标为 `quarantined`，其他 worker 看不到短暂的 `failed`，因此不会整池停机。Passed 仍走完整输入与生命验收。带完整 observation 的 Failed 只有明确的 cleanup `TimeoutException` / `EnsureWithinDeadline` 才进入该重试，不能当标签。`InvalidObservation`、配置和来源问题仍先诊断，该 worker 以非零退出后池会收尾，不能批量隔离掩盖。同一 worker 连续隔离三个不同任务且其间没有 complete，才按系统性问题停止该 worker。不要把单场原生 `ProcessExited` / `Timeout` / `Failed` 再当成整池停止条件。内存预留以 session 为准（现为 0）：运行中的 worker 不因可用内存降到某条线而统一收尾；新启动仍估算每 worker 的 `worker_start_gib`。

待处理队列少于 12,000 场时读取下一页真实局。公开导出接口为 `https://spire-codex.com/api/exports/runs`（开发者文档中的 `/api/runs/export` 当前返回 404）。每页最多 1,000 份，至少间隔 31 秒，尊重 429 Retry-After。固定 submitted-at 时间窗和游标，gzip 完整性验证与全部导入后才推进游标；本地页与来源记录支持断点恢复。队列空时等待来源，不生成新构筑。

2026-09-07 起启用 `--backfill-dir`。现有 `data/external/spire-codex` 新上传来源起点仍为 2026-09-05 UTC，游标原样接续；历史独立目录 `data/external/spire-codex-history` 先扫描 `[2026-08-29, 2026-09-05)` UTC 最近缺失一周，再以不带时间过滤的有限分页扫描全部公开存档，包括缺少 submitted_at 的旧记录。没有放宽 0.111.0 版本或 Silent/A10 限制；旧版本只记来源页，不生成标签。完整存档会与已采来源重叠，由导入身份与任务主键去重，旧 complete 及 attempts 不重做、不覆盖。

两条来源共用 `export-rate.json` 的持久化请求预算和锁，429/服务故障退避同时作用于两者。到期的新上传来源优先；它每个窗口结束后的 300 秒等待供历史扫描使用。`plan.json` 记录两阶段进度，每阶段 `cursor.json` 保留固定范围，只有接口不返回 X-Next-Cursor 才完成（不能按空页或不足 1000 行判断）。全部历史完成后只继续新来源同步，不停止采集。`latest.json` 记录最近历史页的匹配和入队数量。控制器恢复须保留 `--backfill-dir`，不得清空或手动推进任何游标。接口分页语义依据[官方导出实现](https://raw.githubusercontent.com/ptrlrd/spire-codex/main/backend/app/routers/exports.py)。

备份先捕获新来源游标、历史 plan 和两阶段游标，再固定数据库读取快照，保证恢复位置不会领先于备份中的导入记录。当前轮换槽在 session 的 `backup_destination`（现为 `backups/01-active-8s`）。历史元数据保存为每个备份槽内 `source-backfill/`；恢复时放回 session.backfill_dir，保留新来源原 cursor.json。较早游标允许重放来源，任务去重保护成功标签。缺少历史元数据时必须检查备份日期和历史启用记录，不能凭猜测跳页。

状态文件名随活动库变化（现为 v3）：

```bash
.venv/bin/python -m damage_model.cli status
cat data/collection-session.json
# 由活动库路径派生，例如：
# data/collection-real-runs-v3.continuous.json
# data/collection-real-runs-v3.parallel.json
cat data/external/spire-codex/latest.json
cat data/local-backup.json
```

用户要求停止时，先停止已核实 PID 的控制器，再对每个当前 runtime 的 data_dir 写入 `collector.stop`，让在途战斗完成；确认 running=0 后再按当前备份方案生成最终 SQLite API 快照。不得直接复制活动主库、不删除失败记录。备份会按数据库实际文件名保存，因此旧库和新库备份可以并存。

2026-09-07 13:33 的暂停及当时的 v2 / 2 秒启动命令只作历史记录，不能用来恢复当前 8 秒批次。
