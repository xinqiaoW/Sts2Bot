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

模拟器超过请求截止时间后先终止进程；发送 SIGKILL 后若内核尚未完成进程回收，worker 保持所有权并每 60 秒记录等待事件，直到确认退出。此时不启动下一次模拟器请求，战斗本身的 120 秒截止时间不变，超时仍按失败处理。

写锁与结果恢复遵循以下规则：

- 领取、提交及控制器写入只在明确未进入写事务时等待锁，不重放事务内语句或不确定的提交，不消耗战斗尝试。控制器等待期间保留候选与生成序号，并响应停止请求。
- 来源导入整页完成后才推进游标；中断后复用原游标与已校验缓存页。此前已提交的任务由身份去重，不清空重导。
- 提交前重新核对回执、租约和 attempt。若租约在等待期间被替换，重新读取归属；只有存在唯一且内容为 `LeaseExpired` 的 expired attempt，并确认旧租约已释放，才将原回执归档到 `expired-results/` 后继续。归档不生成标签、不覆盖新结果；其他冲突保留回执并停止诊断。

已完成、已隔离任务不自动重打，有效租约不能强行抢占。

多进程写入 WAL 数据库须使用包含 [WAL-reset 修复](https://www.sqlite.org/wal.html#the_wal_reset_bug)的 SQLite；3.51 分支至少为 3.51.3。使用私有 `_sqlite3` 与 SQLite 动态库的部署，应让采集、备份和查看工具通过同一 `code_root` 加载，并核对实际进程映射；共享 `.venv` 的默认 SQLite 版本不代表部署进程的版本。

停止同一实例：

1. 在主库旁创建 `.continuous.stop`，例如 `<实例>/db/real.continuous.stop`，阻止控制器补充或启动新池。
2. 向已核实属于该实例的 `tools.collect_simulator` 进程发送 SIGTERM，或在其前台按 Ctrl+C。该入口会给各 runtime 写入 `collector.stop`，并等待自己启动的持续采集池退出。若是独立或被接管的池，还须分别请求池停止。
3. 核对池与 worker 退出、各库 running=0，再做最终一致性备份。池因人工中断记为 `failed` 时，结合退出原因判断。

正常停止后，核对原发布包、实例配置与锁，移除相应的 `.continuous.stop`，再运行原命令。池启动时会清除其 runtime 中的 `collector.stop`，因此不能只靠该标记维持长期暂停。更换发布包或 worker 数须使用新实例目录。

异常退出后还须检查待提交回执、孤立租约和池状态。旧心跳仍写着 `collecting`、存在 running 任务或回执冲突时，直接重跑原命令可能被控制器拒绝；应先按数据库中的租约与 attempt 处理，不能只改状态文件或清空任务来绕过检查。

## 旧库异常时继续采集

旧库修复与新数据采集可以分开进行。旧实例停止且确认没有进程持有其锁后，保留数据库、对应 WAL、回执和来源元数据，在可正常读写的健康存储上选择新的空目录，以同一发布包启动新实例。新目录具有独立队列、runtime、日志和备份，旧库留待副本核验或恢复。

新实例默认重新扫描来源，不会自动继承旧游标或跨实例去重。若要接续来源位置，须单独迁移已核实的来源游标与扫描范围；旧库未完成任务仍留在旧库，不能视作已经迁入。新旧数据可能重叠，合并时按教师兼容性及稳定任务身份去重，保留来源和血缘。

文件可读性、数据库完整性和索引正确性分别验证，数据库修复先在副本上进行。若索引统计出现同一状态的重复分组或查询报损坏，计数应视为不可信，不能据此估算数据损失。

## 备份

`tools.local_backup` 对单库维护两个轮换槽，显式传入 `--db`、`--directory`、`--state`；默认每轮完成后等待 300 秒。多个备份进程可共用 `--snapshot-lock`，串行复制、校验和计算摘要。

默认 `--method backup` 使用 SQLite backup API，WAL 读事务只在复制期间保持；`--method vacuum-into` 通过只读源连接生成独立逻辑快照。两种方式都在关闭源连接后检查副本，完成整库 `quick_check` 和 SHA-256 校验才发布清单。校验失败不覆盖已有成功备份。

`VACUUM INTO` 保留逻辑记录和显式主键，但可能改变没有 `INTEGER PRIMARY KEY` 的表的隐式 ROWID，见 [SQLite 说明](https://www.sqlite.org/lang_vacuum.html)。恢复及跨备份比对时应使用稳定任务 ID；使用这类副本替换查看页来源后，应重建其增量缓存。

活跃库通过一致性快照备份，不分别复制数据库和 WAL。停机保全原始文件时，数据库与尚未合并进主库的 WAL 须作为匹配集合保存。核对备份状态、摘要、检查结果和任务计数；恢复点间隔包含等待及整轮耗时，同盘双槽不能替代异机容灾。

`tools.local_backup` 的自动元数据收集仍按旧 `data/collection-session.json`、`data/external/` 布局查找，**不会自动完整打包模拟器实例**。备份模拟器时，须先另存 `simulator-session.json`、`active-collection.json`、runtime、发布包及其引用资源、`source/` 中的 plan 和游标，再导出三个数据库。保留较早游标可幂等重放，不能跳过尚未导入的页。

历史补采的串行多库备份见[补采工具](../tools/one_off/README.md)，其运行目录与元数据要求不适用于模拟器实例。

## 日常检查

读取主库旁的 `.parallel.json`、`.continuous.json` 和各库备份状态，并核对心跳时间、实际进程和锁；产出看近期有效 complete 增量。慢导入、建索引或启动校验可能暂不刷新状态，须结合日志及 CPU、I/O 判断。教师核对应覆盖三个库，不能只抽查一条配置。控制器及备份工具在磁盘剩余空间低于 20 GiB 时拒绝继续相应操作，部署时还需为 WAL、日志和备份槽预留增长空间。

只读查看使用[数据页面](data-viewer.md)或显式只读 SQLite 连接。`damage_model.cli status` 会初始化 `Store`、设置 WAL 并确保表和索引存在，不是纯只读检查；其默认库与配置仍是历史 v2 / 2 秒，使用时须显式指定目标。环境见[运行环境](runtime.md)，验收见[验证与审计](validation.md)。
