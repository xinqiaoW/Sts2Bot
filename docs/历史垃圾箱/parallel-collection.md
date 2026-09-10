# 并行采集

当前活动库是 `data/collection-horizon.sqlite`，状态 `data/collection-horizon.parallel.json`，日志 `logs/parallel-horizon.log`。修复搜索末尾的必备工具选牌后使用新老师重新采集，旧库的 918 个标签保留。原来的 8 场超时已全部完成，详见 [恢复记录](horizon-recovery.md)。下方扩容吞吐为旧版历史观测。

2026-09-06 用户要求缩为 4 worker 继续采集。当前覆盖参数为 `--reserve-gib 4 --worker-start-gib 2`，总启动门槛 12 GiB；运行时保留 4 GiB。下方的 8 worker、32 GiB 和吞吐数字均为之前配置。最新持续运行设置见 [持续采集](../continuous-collection.md)。

持续控制器接续后的新池日志为 `logs/continuous-pool.log`，控制器日志为 `logs/continuous.log`。旧 `data/parallel.pid` / `data/round1.pid` 只记录首批，不作为后续进程依据；以最新状态、进程命令行和实际锁为准。首批训练后的自动接续见 [continuous-collection.md](../continuous-collection.md)。

采集的主负载是 CPU 原版战斗与求解器搜索。增加独立游戏进程，共享 SQLite 任务队列与只读游戏资源；每个进程拥有独立 Wine prefix、存档目录、协议文件和日志。单场搜索仍为 Medium、DOP 1、2000 ms，老师配置及数据口径不变。

用 `tools.prepare_parallel_runtimes` 从**已停止的专用模板**创建隔离环境；不能把正在工作的 prefix 直接当模板。该命令遇到已存在的目标目录拒绝覆盖。

```bash
python -m tools.prepare_parallel_runtimes \
  --base configs/runtime-wine-pilot.json \
  --template .runtime/prefix-template-parallel --count 3 --start 1
```

模板在本项目 `.runtime` 内用 Wine 创建，停止模板的 Wine 服务后复制采集存档。保留游戏解锁状态，关闭教学弹窗。启动器通过运行时 DLL 哈希检查同一老师，通过目录锁阻止同一存档被重复使用。

```bash
python -u -m tools.collect_parallel --db data/collection-horizon.sqlite \
  --runtimes configs/runtime-wine-pilot.json configs/runtime-worker-01.json \
  --reserve-gib 32 --limit-per-worker 6080 --train-after
```

池状态持续写入 `data/collection-horizon.parallel.json`，每个 worker 的日志分别保存在 `logs/runtime-worker-XX-worker.log` 和 `logs/worker-XX-game.log`。成功样本额外记录 worker 名称和进程 ID，便于计算吞吐；这些字段不是模型输入。

SQLite 使用事务原子领取与租约，多个连接不会领取同一个有效任务。任一失败出现后，其余 worker 完成手头战斗并停止领取。可用内存低于 32 GiB 也会停止本池，保留现场。原始数据不会因停止或扩容被删掉。

四进程测试发现一例上游缓存缺陷：原生 `MaxEnumValueCache` 的非并发字典被后台问题报告与主线程同时写入。后续实测确认复用进程的第 4 场也可能触发，故检测覆盖每个请求的新日志字节，同时要求该类型名和明确的字典损坏异常。命中后终止本 worker 持有的游戏进程、保存诊断、重新排队，最多 3 次尝试；下次请求会重置日志检测起点，旧异常不会污染新场次。其他异常或普通超时不自动重试；达到上限停止。未结束战斗不生成标签，这个恢复处理不修改求解器 DLL、原版游戏或搜索预算。

需要让某个 worker 完成当前战斗后退出时，在对应 `data_dir` 创建 `collector.stop`；下一次领取前生效。完成所有待处理和正在执行的任务后，整个池才允许训练。有限测试批次还有未完成任务时不训练。

另一个已确认的运行环境故障是 Wine 原生页错误。只有进程确实退出，且本请求日志同时出现 `wine: Unhandled page fault on ...` 和 `starting debugger...` 时，才归类 `NativeWinePageFault` 并使用同一个最多 3 次尝试机制。普通进程退出、未知错误和战斗超时仍停止。进程已退出时也清理其专属进程组，避免遗留调试器；旧请求日志不会触发新请求的重试。

凌晨巡检确认了原生菜单清理断言：本请求战斗结束进入 `stage=cleanup` 后，Godot 在创建 `NInputSettingsEntry` 时发生 `cowdata.h:187` 空数组越界并退出，结果文件尚未写出。`NativeMenuCleanupFailure` 要求当前 runId 的清理阶段、精确越界断言、输入设置/加载主菜单栈及 `Fatal error. 0xC000001D` 同时出现，而且进程已退出；仍共用每任务最多 3 次尝试。单独退出码、其他阶段和其他请求的旧日志不匹配。重跑完整独立战斗，不从动作日志拼接标签，也不更改老师 DLL。

第二批另确认一例清理阶段的 Godot 对象终结器访问冲突：当前 runId 的 `stage=cleanup` 后同时出现 `Fatal error. 0xC0000005`、`Godot.GodotObject.Dispose(Boolean)`、`Godot.GodotObject.Finalize()` 和 `System.GC.RunFinalizers()`，且游戏进程已退出，才归类 `NativeFinalizerCleanupFailure`。同样每任务最多 3 次尝试，保留原失败证据并重跑完整对战；战斗中的一般访问冲突不匹配。

监控查询按 `attempts.finished` 范围读取近期事件。`attempts_recent(finished,status,job_id)` 覆盖时间范围扫描，`attempts_job(job_id)` 支持查找单场历史；避免每次巡检多次读取含大结果载荷的完整 attempts 表。给已有数据库补建索引不会改变标签或老师版本。

不要同时运行两个正式 supervisor。试验池可在已有 worker 旁边运行有限任务；正式切换时要先结束旧 supervisor，避免重复训练或错误报告完成。被中断的任务保留尝试记录并重新排队，不能伪造终局标签。

## 2026-09-05 实测

扩容前：256 逻辑核，CPU 约 9.5%，可用内存约 61.9 GiB，原采集进程约 1.9 GiB RSS；短采样没有持续 swap 读写。GPU 已有其他任务，采集扩容没有使用 GPU。

4 进程稳定区间，60 秒完成 27 场，约 1620 场/小时，可用内存约 57 GiB。第二次有界试验成功完成，已识别冷启动缓存故障的自动检测/重试在真实进程上触发并恢复。

正式切换到 8 进程后，连续 60.01 秒完成 **46 场**，约 **2760 场/小时**；每个 worker 都产出 5–7 场。CPU 平均 12.1%，I/O wait 2.7%，采样可用内存最低约 49.8 GiB。见 `evidence/parallel-8-throughput.json`。不同目标和卡组的耗时会变化，不把这一分钟视为长期吞吐保证。

切换时精确结束原 supervisor、worker 及其持有的游戏进程，记录并重排 1 个中断任务。正式池 PID 写入 `data/parallel.pid` 和 `data/round1.pid`；旧 `collection.run.json` 标记为 superseded，避免再读取旧进程状态。

Python 测试：22 项全测通过；增加显式退出信号处理后，另行验证优雅停止，并增加子进程测试确认 SIGTERM 会清理 worker 持有的游戏进程。没有重编译或更改 CombatSolver DLL。
