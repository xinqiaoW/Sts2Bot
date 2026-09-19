# 2026-09-19 历史种子补采部署

维护分支：`codex/targeted-24-seeds`，代码在 01 的 `/data2/pl/ImageTask/wxq/Projects/Sts2Bot`。执行和数据在 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot`。

用户最终选择固定 25 个 worker。25 worker 的 10 分钟压测完成 543 场，覆盖 43 个编组，记录到 5 次原生失败；40 档按用户要求中断并正常排空，60/80 档未执行。单场搜索仍为 8,000 ms、DOP 1，不修改锁竞争失败处理。

## 生产运行目录

`data/targeted-seed-backfill-20260919/` 保存：

- `deployment.json`：部署提交及逐文件 SHA-256；`deployment-before/`：被替换文件的原副本。
- `prepare-process.json`、`logs/prepare.log`、`prepare-report.json`：完整历史扫描和建队列记录。
- `queues/backfill-manifest.json` 与三个 `*.backfill.sqlite`：独立历史补采队列。
- `runtimes.json`、`runtimes/`：25 个隔离 runtime 的配置；游戏日志在 `logs/game-NNN.log`。
- `pool-process.json`、`logs/pool.log`：正式采集启动命令和进程信息。
- `queues/collection-real-runs-v4.backfill.parallel.json`：现有 pool 的实际状态、各来源数量和 worker PID。
- `backup-process.json`、`logs/backup.log`、`*.backup.json`：备份启动记录和各库的快照状态。

正式采集沿用 `tools.collect_parallel --continuous-workers`，只消耗已生成的有限队列，不启动新构筑生成器。原有失败处理保持原样，异常停止后应先诊断，不应盲目重启或重置数据。

## 数据范围

读取 `collection-real-runs-v4.sqlite`、`collection-mutations-v2.sqlite`、`collection-targeted-mutations-v1.sqlite`。新版库通过 `prior_collected_inputs` 和保留的构筑血缘覆盖 real-v3/mut-v1；按构筑–编组–种子跨版本去重。预览为 203,379 个组合、4,067,580 个额外种子任务，最终以 `prepare-report.json` 为准。

仅补充目标编组种子索引 4–23。少数原始四种子未全部成功的组合仍保留原状，不能把“配置 24 种子”理解为所有组合最终一定有 24 个有效结果。所有原库保持原始数据，不将多档压测的重复输入导入生产训练集。

每批 1,000 个完整组合原子提交，一次性建库连接使用 256 MiB 缓存和 64 MiB WAL 自动检查点阈值，保持原有持久化级别。准备中断可运行原建队列命令恢复，已有任何状态的任务都不重置。补采已经开始后，不要并发重跑准备命令。恢复执行时 `jobs_added` 是本次新写入量，总量需结合 `existing_extra_seeds` 和最终队列计数。

## 备份

原库冻结后保留其已完成快照，在备份进程空闲时停止重复全量复制。新库使用 `tools.one_off.backfill_backup`，首次延迟 300 秒，三个库依次调用原有、带 SQLite 检查和校验和的快照实现；一轮完成后等待 3,600 秒。每库保留两个轮换快照，位于 `backups/targeted-seed-backfill-20260919/`。

这是降低同一磁盘并发全库复制开销的取舍：恢复点间隔约为一小时加整轮备份耗时，不再是原来的五分钟加备份耗时。收到 SIGTERM/SIGINT 时，新备份程序完成当前快照后退出。备份仍位于同一磁盘，不提供磁盘损坏时的异地恢复。

停止采集应向 `pool-process.json` 记录的、命令仍匹配的 pool PID 发送 SIGINT，并等待 `.parallel.json` 和 worker 退出状态确认排空。原 pool 将人工中断也标记为 `failed`，须结合错误内容判断；不要因为状态标签自行重置任务。

本目录下工具仅用于本次补采，生产模块不依赖它们；补采、数据验收和备份完成后可单独移除。
