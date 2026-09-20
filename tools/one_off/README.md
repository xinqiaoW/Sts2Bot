# 一次性历史种子补采

本目录把历史构筑在指定编组上的战斗种子从原索引 0–3 扩展到 0–23，只生成缺少的索引 4–23。源码在 01 的 `/data2/pl/ImageTask/wxq/Projects/Sts2Bot`，执行和数据放在 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot`。

正常采集由 `configs/real-runs-8s.json` 的 `encounter_seed_policy` 使用同一份 43 编组名单，名单内 24 个种子、其余 4 个；重复构筑不新增任务。正常采集不调用本目录，规则见[持续采集](../../docs/continuous-collection.md)。

## 数据范围与去重

工具读取输入库的 `jobs` 和 `prior_collected_inputs`，以 `(build_id, target_id, seed)` 跨库、跨兼容适配器去重。只有名单内、原索引 0–3 至少有一个已完成结果的构筑–编组对纳入补采；没有完成样本的组合不纳入。它不会把每个构筑与全部 43 个编组配对。

索引 4–23 中已有任意状态任务或历史记录的种子均跳过，不重置失败、隔离、运行中任务或 attempts。原四个种子有失败时，不补打原索引；`partial_original_pairs` 和 `missing_original_seeds` 报告缺口。24 个计划种子不等于 24 个有效结果。

种子仍为 `digest(['battle', battle_seed, index])[:16]`，原索引 0–3 及任务 ID 不变。新战斗使用当前协议 3，教师按已有协议 2 → 3 兼容规则检查，其他游戏和搜索参数必须一致；旧标签不改写。

每个输入库生成独立的 `*.backfill.sqlite`，保留构筑、来源窗口、family/split、变异策略历史、血缘和 focus，不写原库或复制旧结果。来源顺序决定重复组合的归属；修改来源顺序、种子配置或教师后，应使用新的输出目录。

real-v4 与 mut-v2 保留了旧 real-v3 / mut-v1 的完成输入索引及构筑血缘，已核验的这批数据可以使用 real-v4、mut-v2、targeted-v1 三库覆盖五个历史来源。换用其他库时必须重新确认覆盖；去重索引不能代替训练需要的旧结果。初始范围和数量依据保存在[预览报告](preview-20260919.json)与[独立核对报告](count-audit-20260919.json)，它们是固定批次记录，不是实时进度。

## 数量口径

一个构筑对应两个符合条件的编组，计为一个构筑、两个组合，最多追加 40 场。以下字段分别使用不同单位：

| 字段 | 含义 |
| --- | --- |
| `stored_unique_builds` | 输入库中全部唯一构筑，含尚无完成任务的构筑 |
| `eligible_builds` | 至少一个组合符合补采条件的唯一构筑 |
| `eligible_pairs` | 符合条件的唯一构筑–编组对 |
| `eligible_pairs_per_build` | 每个构筑对应多少个合格组合的分布 |
| `extra_seed_slots` | `eligible_pairs × 20`，等于 `jobs_to_add + existing_extra_seeds` |
| `pairs_to_extend` | 仍需写入缺失种子的组合数 |
| `expected_output_jobs` | 对应输出库原有任务数加本轮待追加任务数 |

断点续跑时，`eligible_pairs` 保留完整范围，`jobs_added` 只表示本轮新写入量。来源构筑数可能重叠，不能直接相加代替全局去重数；队列就绪校验使用实际准备报告中的总数。

## 预览与生成队列

先部署相互依赖的采集源码、配置和本目录工具，保留执行副本的 runtime 配置与数据。默认命令只读预览，不创建补采库或启动游戏：

```bash
cd /data1/pl/ImageTask/wxq/Projects/Sts2Bot
.venv/bin/python -u -m tools.one_off.backfill_targeted_seeds \
  --sources data/collection-real-runs-v4.sqlite \
            data/collection-mutations-v2.sqlite \
            data/collection-targeted-mutations-v1.sqlite \
  --output-dir data/targeted-seed-backfill/queues \
  --report /tmp/targeted-seed-backfill-preview.json
```

扫描和来源校验需要读取历史数据，进度写入标准错误。缺少输入文件会报错。来源库按希望的归属优先级排列；只有确认新版库完整保留旧输入索引和构筑血缘时，才可省略旧库。

正式生成时，先暂停来源导入和变异生成，排空来源库正在运行的战斗，保持扫描输入稳定；也可使用一致性备份。工具拒绝带 running 任务的来源库。在同一命令中添加 `--apply`，并把 `--report` 改成 `data/targeted-seed-backfill/prepare-report.json`。这一步只生成队列，仍不启动游戏。

输出目录中的 `backfill-manifest.json` 固定来源、教师和种子规则，目录锁防止两个准备进程同时写入。每批 1,000 个完整组合原子提交，建库连接使用 256 MiB SQLite 缓存及 16,384 页 WAL 自动检查点阈值（4 KiB 页时约 64 MiB），保持持久化提交。中断后可用相同命令恢复，已有任务不重置；不要并发启动第二个准备进程。

## 执行补采

使用现有 worker 池消费有限队列，不启动 `collect_continuous`。以下三个 runtime 仅作命令示例，执行前必须替换为已经核实空闲且相互隔离的配置：

```bash
.venv/bin/python -u -m tools.collect_parallel \
  --db data/targeted-seed-backfill/queues/collection-real-runs-v4.backfill.sqlite \
  --fallback-db data/targeted-seed-backfill/queues/collection-mutations-v2.backfill.sqlite \
  --targeted-db data/targeted-seed-backfill/queues/collection-targeted-mutations-v1.backfill.sqlite \
  --config configs/real-runs-8s.json \
  --runtimes configs/runtime-worker-01.json configs/runtime-worker-02.json configs/runtime-worker-03.json \
  --reserve-gib 0 --worker-start-gib 2 --continuous-workers
```

并发数由 runtime 列表决定；资源参数应按实际限额设置。三个来源沿用 2:1:1 领取周期。与正常采集并行时必须使用不同的 Wine prefix、`data_dir` 和独立数据库。补采队列耗尽后结束，不会自动开始采集新构筑。

## 已提交队列与自动接续

`finish_backfill_startup.py` 用于先消费已提交的真实补采任务，同时让同一个准备进程继续写完剩余队列。它是固定 25 worker 的接续工具，不是通用启动器。已部署运行目录为 `data/targeted-seed-backfill-20260919/`；具体阶段、任务量和进程以该目录的状态文件为准。

| 运行文件 | 用途 |
| --- | --- |
| `deployment.json`、`deployment-before/` | 部署版本、文件摘要与原副本 |
| `prepare-process.json`、`logs/prepare.log`、`prepare-report.json` | 准备进程与最终报告；报告在生成结束后写出 |
| `queues/backfill-manifest.json`、`queues/*.backfill.sqlite` | 固定输入清单与补采队列 |
| `runtimes.json`、`runtimes/` | runtime 路径列表及独立配置 |
| `bootstrap-pool-process.json`、`pool-process.json` | 初始真实池与切换后三来源池的进程信息 |
| `pipeline-process.json`、`pipeline-state.json` | 接续程序及当前阶段 |
| `queues/*.parallel.json` | 池状态、任务数量与子进程 PID |
| `backup-process.json`、`*.backup.json` | 备份启动参数与各库快照状态 |

接续工具还依赖运行目录内准备好的 `resource_guard.py`。所有队列写完后，它校验各库 `expected_output_jobs`，排空初始池，确认没有运行中租约且 runtime 锁已释放，再启动同一组 25 个 runtime 消费三个队列。结果保留在原补采库中。接续命令为：

```bash
.venv/bin/python -u -m tools.one_off.finish_backfill_startup \
  --run-dir data/targeted-seed-backfill-20260919
```

此工具内部的切换启动参数目前为 `--reserve-gib 32 --worker-start-gib 3`，不自动继承初始池的资源参数。运行前应核对这些固定参数和运行目录的准备情况。准备或采集异常时记录 `needs_diagnosis`，不会替代故障诊断自动重启。

停止带接续程序的补采时，先创建运行目录中的 `pipeline.stop`，防止后续切换。然后根据阶段选择初始池或三来源池，核实 PID 命令行后发送 SIGINT，等待在途战斗排空、worker 退出和 running=0。`resource-guard-stop.json` 同样阻止自动接续。恢复前处理停止原因并核对配置；不能仅因状态为 `failed` 就清零或重置任务。

## 串行备份

备份工具要求运行目录中有 `deployment.json`、`runtimes.json` 和 `queues/backfill-manifest.json`。有最终准备报告时按报告定位数据库；否则使用清单定位已生成队列，尚未生成的库留待后续轮次：

```bash
.venv/bin/python -u -m tools.one_off.backfill_backup \
  --run-dir data/targeted-seed-backfill-20260919 \
  --directory backups/targeted-seed-backfill-20260919 \
  --interval 3600 --initial-delay 300
```

三个补采库依次调用现有一致性快照实现，每库保留两个轮换槽，输出位于备份目录下的 `<数据库名>/slot-a`、`slot-b`。可重复传入 `--additional-db`，将正常采集库加入同一轮；同轮数据库文件名须唯一。先确认没有另一套重复备份进程争用这些目录。

每轮完成后等待 `--interval` 秒，实际恢复点间隔还包含整轮备份耗时。SIGTERM/SIGINT 会让当前快照完成后退出。核对快照摘要、SQLite quick_check 和计数；同盘备份不能替代异机容灾。

## 训练与工具清理

训练时显式纳入需要的历史五个来源和三个补采库，真实补采的 `kind` 为 `real`，其余为 `mutation`，按共享构筑、源局和血缘统一去重划分，见[训练说明](../../train/README.md)。旧看板未适配 24 种子进度，不能以页面的四种子文案判断补采是否完成。

补采、验收和备份交接完成后，可删除本目录的 Python 工具及其测试：`tests/test_targeted_seed_backfill.py`、`tests/test_backfill_backup.py`、`tests/test_finish_backfill_startup.py`。清理代码前先停止依赖这些工具的进程，保留结果数据库、来源清单和备份。正常 24/4 种子逻辑不依赖本目录。
