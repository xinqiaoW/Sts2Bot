# 持续采集与备份

当前入口为 `tools.collect_simulator --continuous`，准备条件见[模拟器采集](simulator-collection.md)。模拟器与历史 Wine 后端共用队列控制器，实例路径、教师和 runtime 分别配置。

## 启动与调度

在仓库根目录执行，将发布包路径替换为实际位置：

```bash
.venv/bin/python -m tools.collect_simulator \
  --bundle /absolute/path/to/release \
  --directory .local/simulator-continuous --continuous --workers 4
```

每个 worker 使用独立的运行目录，按真实、真实、普通变异、专项变异循环领取任务，空队列允许借用。两个变异队列各低于 600 个 pending 时补充 100 个构筑，不要求真实队列为空。详见[来源与调度](source-versions-and-scheduling.md)、[变异规则](mutations-8s.md)。

模拟器实例中的 `active-collection.json` 固定三个数据库，`simulator-session.json` 固定发布包身份与 worker 数，`runtime-*.json` 定义各 worker。控制器、采集池和 worker 分别持有独占锁；启动前核对同一实例的配置、进程和锁。PID 与状态文件只是线索，不能单独证明进程仍在运行。

模拟器入口始终使用仅采集模式。直接运行 `tools.collect_continuous` 时须显式传入 `--collect-only` 及整套数据库、配置、目录、教师和 runtime；示例见[模拟器采集](simulator-collection.md)。`--reserve-gib` 是运行内存预留，设为 0 时关闭基于该预留的排空；`--worker-start-gib` 是新 worker 的启动预算，两者都不是进程实际内存上限。

## 来源补充与种子

8 秒采集策略对专项名单中的 43 个编组安排每构筑–编组 24 个种子，其余编组 4 个。真实导入、普通变异和专项变异共用该规则；前 4 个种子及任务 ID 保持兼容。配置在进程启动时加载，不会自动重扫来源或扩充已排队任务。

正常持续采集按构筑 ID 去重：真实导入检查三个活动库，重复构筑不再添加编组或种子任务；真实库中的重复构筑仍保留来源关系。两个变异生成器也做跨库构筑去重。历史旧构筑的额外种子由[独立补采工具](../tools/one_off/README.md)负责。

真实 pending 少于 12,000 时允许拉取下一页，单页导入可使队列暂时超过水位。实时与历史来源共用至少 31 秒的请求间隔及失败退避，整页处理完才推进游标；`compatible-archive-v1` 使用独立游标扫描兼容旧版本。来源等待不阻止已有队列采集。

## 故障、停止与恢复

战斗失败保留请求、日志和全部 attempts，按 `retry_then_quarantine_v1` 每任务最多 3 次尝试；仍失败则写入 `job_quarantines`，其他任务继续。失败或超时不能充当标签。一个 worker 连续隔离 3 个不同任务且其间没有成功时，按系统性问题中止诊断。

领取或提交结果时，只有明确发生在 `BEGIN IMMEDIATE` 前的 `ClaimBusyBeforeBegin` / `WriteBusyBeforeBegin` 才等待写锁并重试，不消耗战斗尝试。提交重试重新核对持久凭据、租约和已有 attempt；事务内异常、租约冲突及结果不一致仍报错。已完成、已隔离任务不自动重打，有效租约不能强行抢占。

停止同一实例：

1. 在主库旁创建 `.continuous.stop`，例如 `<实例>/db/real.continuous.stop`，阻止控制器补充或启动新池。
2. 向已核实属于该实例的 `tools.collect_simulator` 进程发送 SIGTERM，或在其前台按 Ctrl+C。该入口会给各 runtime 写入 `collector.stop`，并等待自己启动的持续采集池退出。若是独立或被接管的池，还须分别请求池停止。
3. 核对池与 worker 退出、各库 running=0，再做最终一致性备份。池因人工中断记为 `failed` 时，结合退出原因判断。

恢复前处理停止原因，核对原发布包、实例配置与锁，移除相应的 `.continuous.stop` 后再运行原命令。池启动时会清除其 runtime 中的 `collector.stop`，因此不能只靠该标记维持长期暂停。更换发布包或 worker 数须使用新实例目录。

## 备份

`tools.local_backup` 对单库维护两个轮换槽，显式传入 `--db`、`--directory`、`--state`；默认每轮完成后等待 300 秒。多个备份进程可共用 `--snapshot-lock`，串行复制、校验和计算摘要。

备份使用 SQLite backup API；WAL 读事务只在复制期间保持，随后关闭源连接并检查独立副本。不能直接复制活跃数据库或 WAL。核对成功状态、摘要、SQLite quick_check 和任务计数；恢复点间隔包含等待及整轮耗时，同盘双槽不能替代异机容灾。

`tools.local_backup` 的自动元数据收集仍按旧 `data/collection-session.json`、`data/external/` 布局查找，**不会自动完整打包模拟器实例**。备份模拟器时，须先另存 `simulator-session.json`、`active-collection.json`、runtime、发布包及其引用资源、`source/` 中的 plan 和游标，再导出三个数据库。保留较早游标可幂等重放，不能跳过尚未导入的页。

历史补采的串行多库备份见[补采工具](../tools/one_off/README.md)，其运行目录与元数据要求不适用于模拟器实例。

## 日常检查与历史原生入口

读取主库旁的 `.parallel.json`、`.continuous.json`、备份状态，并核对实际进程和锁；产出看近期有效 complete 增量。慢导入、建索引或启动校验可能暂不刷新状态，须结合日志及 CPU、I/O 判断。`jobs_teacher` 索引用于完整核对三个库的教师，不能只抽查一条配置。

历史 Wine 执行副本位于 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot`，真实 v4、普通变异 v2、专项变异 v1 的路径由该副本的 `data/collection-session.json` 和 `data/active-collection.json` 确认。只查看历史真实库状态的命令为：

```bash
cd /data1/pl/ImageTask/wxq/Projects/Sts2Bot
.venv/bin/python -m damage_model.cli \
  --db data/collection-real-runs-v4.sqlite --config configs/real-runs-8s.json status
```

这些旧 CLI 默认仍指向 v2 库和 2 秒配置，操作其他库时须显式指定参数。历史补采有独立队列与停止流程。环境见[运行环境](runtime.md)，验收见[验证与审计](validation.md)。
