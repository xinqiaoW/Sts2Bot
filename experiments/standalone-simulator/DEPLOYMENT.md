# 独立采集发布目录与回退

当前候选已修复 GAMBLING_CHIP 的抽牌/Sly 自动出牌顺序，教师 `116098fd…`、宿主 `ff2a6006…`。四项原生完整状态最小差分、固定失败开局、原生新/旧路线重放通过；全量 10,008 场录像复核已启动，尚未通过最终验收。证据见 [换牌时序修复](../../vendor/CombatSolver/coverage/gambling-chip-order-repair-20261001.json)。正式生产仍未启动。

新候选发布为 `candidate-release-v4`（提交 `0003d8c`）；新版原生证据要求教师身份与发布完全相同，旧教师录像仅作回归，不改写其身份。为此另行准备 `standalone-gambling-chip-validation-20261001`：10,500 个实际构筑、80 个目标，与旧面板的构筑交集为零；仍要求至少 10,000 场和 500,000 个动作检查点。控制器等待旧录像回归排空并独立审计通过后，才启动 24 个原生工作进程。新版单核配对性能另在 `performance-v4` 运行。此处仅记录已启动/已准备工作，详见 [验证启动清单](gambling-chip-validation-launch-20261001.json)，不表示验收完成。


`rollout-v3` 已停止且不通过，其交接绑定不能用于激活。修复候选位于 `standalone-rollout-readiness-20260929/soak-quarantine-diagnostic-0002`；必须使用新发布、新验收和从零计时的 24 小时试采。以下 v3 性能、校准、回退和启动记录均为历史证据。


上一候选宿主 `554f9cc1…` 已通过 [万构筑完整状态验收](native-victory-guard-repair-20261001.json)：10,008 个构筑、80 个目标、534,775 个动作点，以及每场完整终局和有序出牌区一致，独立审计确认全部采集锁已释放。当前版本性能、并发校准和回退演练均已通过，正式生产会话尚未切换；该轮试采已因开局换牌规则差异停止，不能用于正式切换。

2026-10-01 候选发布冻结在 `/data1/pl/ImageTask/wxq/Projects/standalone-rollout-readiness-20260929/candidate-release-v3`，准备清单为同目录 `candidate-preparation-v3.json`。后台 `automatic-acceptance-v3` 顺序执行性能、准备队列、并发校准、回退和全新 24 小时试采。 新宿主性能已完成 24/24 条且 CPU 绑定全部通过：单核有效吞吐量 198.59 对 101.59 条/小时（约 1.95 倍），每条峰值 RSS 的中位数 187.50 对 1601.66 MiB。该结果仅覆盖 6 个冻结输入的两轮反向批次，不是并发选档或规则一致性的替代证据；完整报告及采样限制见上述验收索引。此前 `rollout-v2` 因自主执行胜利断言错误停止，其失败和 16,185 条成功记录均保留，但不能计作新版长跑通过。下文旧的 `formal-handoff-tools-v1` 清单绑定旧候选。新的 `formal-handoff-tools-v2/manifest.json` 已冻结同样经过测试的 12 个工具文件，并绑定新版发布、`rollout-v3/plan.json`、完整状态审计、性能报告和原生备份。它提供新版 prepareQueues→prepareAudit→prepareDeployment→runDeployment 命令；所有交接阶段均尚未启动，必须先通过本轮剩余验收。

历史发布 `/data1/pl/ImageTask/wxq/Projects/standalone-10000-builds-20260924/terminal-sly-release` 的宿主为 `df11b26d…`。当时的 10,036 构筑、532,666 个动作检查点缺少后来增加的完整终局/出牌区验证，不是当前候选的通过证据。旧发布与原生回退资料继续保留；新候选必须重新冻结产物、教师与来源身份。

2026-10-01 并发校准共 16 个批次、2,560 场，零失败、零隔离；首组只有 28 个有效配对，因此依既定规则增加 160 个输入，合并后每档有 45 个有效搜索配对。最终选定 24 worker，约 5,954 条/小时，相对 8 worker 的中位展开量比为 0.9859，额外平均掉血为 -0.0641，额外死亡率为 0。32 worker 约 6,188 条/小时，24 worker 已在最快档 5% 以内。回退三阶段均正常退出、释放锁、保存历史并通过备份校验。

已停止的试采曾于北京时间 2026-10-01 01:33:02 启动，24 worker，CPU 范围 64–95，同时执行原生抽检。该轮实际运行 7,682.53 秒，完成 17,941 场后发现一例隔离失败；已排空，不能累计到修复版的 24 小时门槛。原先预计的最早验收时间已失效。

## 冻结发布目录

在原型工作树运行 `release_tool.py create`，提供已验证宿主 DLL、原游戏目录、进度快照、dotnet 和一个不存在的输出目录：

```bash
python experiments/standalone-simulator/release_tool.py create \
  --host-dll <host.dll> --game-directory <game-dir> \
  --progress-snapshot experiments/standalone-simulator/fixtures/pilot-progress-v24.json \
  --dotnet <dotnet> --teacher-config <validated-teacher.json> --output <release-dir>
```

发布包含 `damage_model`、`tools`、`train` 的 Python 代码，正式采集/变异配置、目录数据、实验教师清单、宿主 DLL/runtimeconfig/deps 和进度快照。每个输入文件均记录 SHA256；先完整复制校验，再发布目录。原游戏程序集和 Python/.NET 安装仍是外部依赖，清单记录本次环境，worker 启动仍验证游戏/求解器/宿主与进度身份。这不是独立容器镜像。

校验发布目录：

```bash
python /path/to/release/release_tool.py verify --bundle /path/to/release
```

`runtime-template.json` 固定宿主和进度路径。每个 worker 另建 runtime 文件，填写不同的绝对 `data_dir`；准备队列的教师身份必须与发布目录的 `teacher.json` 相同。正式目标范围策略必须在空库初始化，不能给已有未知范围队列直接改标记。

运行已准备的隔离队列：

```bash
python /path/to/release/release_tool.py run \
  --bundle /path/to/release --module tools.collect_parallel -- \
  --db /path/to/instance/real.sqlite \
  --fallback-db /path/to/instance/mutation.sqlite \
  --targeted-db /path/to/instance/targeted.sqlite \
  --config /path/to/release/configs/real-runs-8s.json \
  --teacher /path/to/release/teacher.json \
  --runtimes /path/to/instance/runtime.json \
  --reserve-gib 4 --worker-start-gib 2 --limit-per-worker 4
```

从实例工作目录启动，以便 logs 和失败证据留在该实例。启动器强制使用发布包的 Python 搜索路径（`-P`、`PYTHONSAFEPATH=1`）、教师、配置和目录数据，并传给子 worker；不需要链接工作树的 configs/catalogs。`tools.collect_continuous` 也可通过同一启动器运行，参数和停止流程见 `docs/continuous-collection.md`。

## 正式切换和回退的剩余步骤

以下是待执行的切换边界，尚未执行：

2026-09-29 核对的正式实例是 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot`，其原生采集会话处于暂停状态；`/data2` 下同名目录中的会话是更早的副本，不能据此恢复生产。当前原生三库分别有 14,519 / 1,138 / 772 个 pending，没有 running；控制器、三库池及 4 个 runtime 的锁均已实测可取得。原生游戏/教师/Ritsu 程序集与原会话身份匹配。上述是准备时的观察，正式切换时仍须重新检查。

回退准备位于 `/data1/pl/ImageTask/wxq/Projects/standalone-rollout-readiness-20260929/formal-handoff-inventory-v2`；已保存会话、活动指针、配置、来源游标与 4 个 runtime，共 19 个元数据文件。三库的一致性备份与逐行恢复比较在相邻的 `formal-native-backup` 目录执行；仅其 `final-report.json` 的 `passed=true` 表示这项备份完成。验收中的模拟器发布和正在运行的验证进程不受此原生备份影响。

1. 保存原生会话、三队列、教师清单、runtime、来源游标和活动指针的一致备份。先停止原生控制器，再排空其池和在途战斗。
2. 独立后端使用自己的队列和冻结教师身份；不改写原生历史 attempts、不把 `StandaloneCompleted` 改为 `Passed`，也不在两种教师之间直接改队列身份。
3. 切换前确认控制器/池/worker 锁均已释放，running=0，旧实例的停止原因已处理；原生回退资料和已验证发布目录都保留。
4. 如需回退，先停止并排空独立实例、保存其全部尝试和备份，再恢复原生活动指针/会话及原生 runtime。有效租约不抢占，过期租约走已有恢复路径。

正式交接前运行独立就绪检查，输出必须使用新的文件路径：

```bash
python tools/verify_standalone_acceptance.py \
  --directory <completed-rollout-directory> --output <formal-readiness.json>
```

该工具持有长跑控制器、三库采集池和 worker 的锁，重新核对发布身份、万构筑审计与性能报告；重算并发选档，读取资源时间线验证内存、OOM 和实际观察到的长跑时长（采样分辨率一秒），防止收尾备份时间代替采集时间。它比较三库与最终备份的 builds/jobs/attempts/隔离记录，并逐场重读原生抽检的原始事件、回放动作状态、完整终局与有序出牌区。实际队列计数、不同构筑抽样比例和 80 个目标覆盖也必须一致。

就绪凭据不等于已启动生产；之后仍须完成原生回退资料复核、独立生产队列与会话准备、活动指针交接和实际采集检查。验收与部署凭据关联原样冻结发布，不改写宿主的原始来源标记或将旧实验结果批量重标为正式标签。

验收和原生三库恢复核对全部通过后，可使用 `tools/prepare_standalone_handoff.py --rollout <completed-rollout-directory> --native-backup-report <formal-native-backup/final-report.json> --directory <new-preparation-directory>` 准备独立待采队列。工具重新执行就绪检查，核对原会话、活动指针、备份身份以及正式配置；游戏规则、标签定义、8 秒搜索预算和 DOP 1 必须保持一致。

新库只将原 pending 输入关联到冻结独立教师，保留原构筑、目标、种子、来源窗口、变异谱系和生成序号。原生已完成、失败和隔离输入保存为既有采集记录以防重复调度；原生结果和尝试仍留在原库及快照，不改身份。准备失败时保留临时库，不覆盖重试。

三库准备后，工具在 `instance/` 下创建所选并发数的独立 runtime、会话草稿和活动指针草稿。实时/历史来源游标及请求频率限制原样取自真实队列快照之前保存的元数据，不能用交接时可能更靠前的游标覆盖。会话固定 16 GiB 余量、每 worker 2 GiB 启动预算、8 秒/DOP 1 的冻结教师；从已验收长跑的实际启动记录固定 CPU 范围和配额，命令用同一 `taskset` 范围执行冻结发布启动器，仍检查原正式活动指针。工具不改该指针、不启动采集。25 项合成测试覆盖队列谱系、游标恢复、CPU 绑定和真实启动器参数解析，不计入实战一致性或长跑数量。

正式持续抽检另用 `tools/standalone_production_audit.py --handoff <prepared-handoff-directory> --rollout <accepted-rollout-directory> --directory <new-audit-directory>` 准备。它核对准备时的三库快照与独立验收结果，冻结抽检代码和计划；输出启动命令但不执行。抽检进程启动时再检查验收、迁移凭据和三库教师身份，读取新追加的成功尝试，并使用现有原生录制、完整逐动作/终局/PlayPile 回放逻辑。数据库在正式采集中会改变，因此运行期间校验迁移和教师身份，不拿准备时的整库哈希否定正常新增结果。

正式模式持续补足至少 1% 不同构筑的选样，并随新目标出现补齐目标覆盖；这个比例表示已选入队列，实际通过量仍以 matched 证据为准。状态差异、选中样本耗尽三次原生录制或其他运行异常会写入 `audit-stop.json` 并退出；已有停止标记或最终报告禁止直接重启。正式监督器在采集前确认 `audit-ready.json` 的进程身份，监测抽检进程与停止标记，发现异常就停止续接并排空。实际生产切换尚未执行；本项 27 个合成/进程测试不构成真实在线抽检通过的证据。当前冻结验收目录不受这些源码改动影响。

`tools/standalone_production_guard.py` 提供监督器的健康检查与排空组件。先冻结经身份核对的三库、runtime 停止路径及锁路径；即使运行中更新会话 PID，停止操作也不会被重定向。排空先阻止控制器续接，再通知 worker 完成当前任务；只有控制器退出、控制器/三库池/全部 worker 锁同时可取得、三库 running 均为零，才报告排空完成。190 秒超时保留停止标记、在途租约和诊断，不抢占或清空任务。

父进程退出守护程序先安装处理函数，再设置 Linux 父进程死亡信号，并核对父 PID 和创建时间；就绪后监督器才可启动采集。监督器被 SIGKILL 时也会写入停止标记，覆盖“控制器已经退出但另一个会话中的池仍运行”的情况。健康检查沿用 16 GiB 内存、50 GiB 磁盘、1% 隔离率，并检测 CPU 配额下降、cgroup 变化/OOM、抽检和备份失败。7 项组件测试包含真实进程、独占锁和 SQLite 在途状态，另有 10 项交接回归通过。

`tools/standalone_production_supervisor.py` 将这些组件接入持续监督循环。它先检查准备凭据，启动父进程退出守护和独立抽检，等待两者真实 PID 的就绪信息及三库首次备份完成，再调用部署入口提供的交接函数，确认活动指针与准备内容一致后启动控制器。备份通过现有本地双槽函数每 30 分钟执行；指针、抽检、备份、CPU/内存/磁盘及持续 worker 内存增长任一检查失败都会进入排空。明确请求停止时，排空后等待抽检结束并保存最终备份；失败时保留原始错误、日志和已完成备份，不自动重试交接。

监督循环的 7 项测试使用真实子进程、锁、SQLite 和实际双槽备份，覆盖正常停止、抽检失败、备份失败、活动指针变化、首次备份失败、旧就绪文件及启动后会话发布失败；与 7 项排空组件测试共 14 项通过。测试中的游戏进程和验收前提为合成替身。

验收及准备完成后，最终部署入口分两步执行：

```bash
python tools/deploy_standalone.py prepare \
  --handoff <prepared-handoff-directory> --audit <prepared-audit-directory> \
  --directory <new-deployment-directory>
# 使用 preparation.json 输出的命令运行冻结入口；此步骤才会交接并启动采集。
python <new-deployment-directory>/control/deploy_standalone.py run \
  --directory <new-deployment-directory>
```

prepare 冻结部署/监督/备份代码及输入身份；run 拒绝变更的代码或既有启动记录。run 持有原生控制器、三池与原 worker 的所有权锁，核对旧 runtime 与原教师程序集，然后逐表比较原生库与回退快照，包括来源记录、变异谱系、生成序号及所有历史尝试，不能仅用任务计数相等放行。正式监督器沿用已校准 CPU 范围和至少同等配额。

交接保存原生会话和指针的原始字节，先更新新实例及原正式会话，再最后发布活动指针。`handoff-journal.json` 记录中断的位置与回退原件；中断不自动改回、覆盖重跑或重新标记任何战斗结果。监督器确认抽检和首次备份后才调用交接；控制器实际启动后登记 PID/创建时间。关闭时更新会话状态，失败保留全部证据。部署、交接与监督回归共 52 项测试通过；仍需在真实验收完成后实际执行并核对新输出，当前正式采集未启动。

当前通过测试的后续工具已从 `f2c9002` 冻结到 `/data1/pl/ImageTask/wxq/Projects/standalone-rollout-readiness-20260929/formal-handoff-tools-v1`。`manifest.json` 固定 12 个文件、候选发布及准备队列→准备抽检→准备部署→运行部署的准确命令；各阶段均尚未执行。工具自身与后续生成的控制代码分别校验身份，不能把这个工具清单当成验收报告或部署完成凭据。

`run_backend_rollback.py` 在隔离实例中演练这一流程：原生队列完成 1 条，切到独立队列并在有效租约期间写入停止标记，排空后备份两库并核对全部尝试，再切回原生完成第 2 条，前后校验发布清单。该演练此前在 2026-09-22 的早期发布上通过；正式切换前应对当前发布重新运行：

```bash
python experiments/standalone-simulator/run_backend_rollback.py \
  --bundle <release-dir> --benchmark <backend-comparison.json> \
  --native-runtime <native-runtime.json> --isolated-native-directory <isolated-dir> \
  --output-root <output-dir> --report <rollback.json>
```
