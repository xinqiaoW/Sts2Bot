# 独立采集发布目录与回退

`rollout-v5` 已因原生抽检启动时的模块名错误停止：冻结原生源码提供 `persistent_capture.py`，抽检仍导入旧名 `persistent_capture_v2`。这不是已发现的战斗状态差异，但抽检没有运行，试采不能通过。该轮运行 32.811 秒、完成 2 场，29 把控制器/池/worker 锁及所有队列零在途已复核；日志、试采报告和失败现场均保留。此前本轮并发校准及隔离回退已通过；回退三阶段退出码为零，原生与模拟器历史、备份快照和四把所有权锁已直接核对。修复提交 `b8d6af0` 按冻结清单中的实际路径加载录制器，并在验收准备时用独立 Python 进程验证导入；93 项相关测试及当前冻结原生源码导入检查通过。真实原生录制与独立回放也已通过：38 个动作检查点、1 个完整终局和有序出牌区一致。所有修复证据位于 `standalone-rollout-readiness-20260929/native-audit-import-repair-20261001`，由验收索引绑定。

修复后的 `rollout-v5b` 已通过并发校准，控制器进入回退演练；全新 24 小时试采尚待开始。新计划 SHA256 为 `47ee968f708690dda86be0a20b27bc93ff92326d16896bd56b090e6cd8543ac1`，保留 16,000 个真实构筑、各 1,000 个变异/定向构筑、86,400 秒、至少 10,000 场和 1% 抽检门槛。战斗宿主、教师、冻结原生源码和已通过的万构筑审计/配对性能均未更改；新入口的真实录制不计入长跑。

v5b 的 16 批校准共完成 2,560 场，零失败、零隔离。首轮 29 对有效限时搜索样本触发补充 160 个输入，全部原始和补充数据合并后有 50 对。逐份读取报告重算与控制器选档一致：24 路 5,909.30 条/小时，32 路 6,110.61 条/小时；24 路达到最快档的 96.71%，选定 24 worker。其展开量中位比 0.98171、额外平均掉血 -0.1328125、额外死亡率 -0.003125 均通过门槛。当前选档及全部报告身份已绑定验收索引，先前 v5 校准结果另列为历史证据。

与新计划配套的 `formal-handoff-tools-v5b/manifest.json` 已冻结，SHA256 为 `4df0db6257d5cca9be7787199850dc212f4b904ac83ed3a799fdd1b5ba61fdb3`。12 个工具逐一与已测试修复源码校验，仅抽检入口及来源校验两个文件相对上一清单变化。全部正式交接阶段尚未执行，仍须完整验收通过并复核原生备份来源；旧 `formal-handoff-tools-v5` 绑定失败的试采目录，不能用于激活。

新版候选 `candidate-release-v5` 已通过新教师万构筑完整状态验收（源提交 `981b116`，教师 `f55809c5…`、宿主 `7d2ed38a…`）。[验收证据索引](boulder-correctness-acceptance-20261001.json) 记录独立审计确认的 10,018 个不同构筑、532,580 个动作检查点、80 个目标，以及每场完整终局和有序出牌区一致；24 个工作进程均正常退出，审计持有全部采集锁。24 次失败采集尝试均保留并复核，只计入各例首次完整录制及其固定动作回放；独立限时搜索的失败尝试与重试可能走不同路线，重试通过不证明失败路线一致。

[原始启动清单](boulder-validation-launch-20261001.json) 固定 10,500 个预选构筑，与前两批面板无交集；达到门槛并排空后剩余 482 个预备构筑未执行。此前 14,548 场保留录像、776,814 个动作检查点回归也已通过，单列为历史录像回归，不合并进新教师数量。当前版本配对性能和并发校准已完成；回退、全新 24 小时试采及正式交接仍待完成，正式采集未启动。

v5 并发校准共 16 个批次、2,560 场，零失败、零隔离。首组有效限时搜索配对为 29 对，按既定规则增加 160 个输入；两组全部保留合并后为 51 对。重新读取全部报告计算的选档与控制器一致：24 worker 为 5,966.18 条/小时，32 worker 为 6,096.51 条/小时；前者达到最快档的 97.86%，按“最快档 5% 内选择更小池”选定 24 worker。24 路的中位展开量比为 0.9693，额外平均掉血为 -0.13594，额外死亡率为 -0.0046875，均满足门槛。输入、16 份报告和选档报告身份见验收证据索引；此项搜索质量校准不代替固定动作完整状态一致性审计。

v5 单核配对测试的 6 个输入按两种后端的正反顺序各运行一轮，24/24 次成功，结果文件、进度快照及 CPU 绑定全部核验通过。模拟器有效吞吐为 215.85 条/小时，原生为 106.92 条/小时，合计吞吐比为 2.0188；两种后端单次耗时中位数之比为 1.7313。进程树峰值 RSS 中位数分别为 190.85 与 1574.95 MiB，采样间隔 20 ms，不含后台 Wine 服务，短命子进程可能漏采。此结果是 6 个输入的单核性能证据，不能替代并发选档、规则一致性或稳定性验收；原生批内复用进程，模拟器每请求启动进程，原生启动和停止成本计入批次，系统缓存未控制。独立限时搜索可能选择不同动作和标签，规则一致性仍依据单独的固定动作完整状态审计。完整报告身份和测量限制见上述验收索引。

v5 正式交接工具已预先冻结到 `/data1/pl/ImageTask/wxq/Projects/standalone-rollout-readiness-20260929/formal-handoff-tools-v5`。`manifest.json` 的 SHA256 为 `0f04751e61b2119e865c487a5eeb77af2d9be5ee59cf97a335d262db20ef2543`；12 个工具文件均逐一确认与此前已验证的 v2 工具和当前源码相同。新清单绑定 v5 发布、试采计划、万构筑审计和配对性能，以及原生备份凭据，并给出 prepareQueues→prepareAudit→prepareDeployment→runDeployment 命令。全部交接阶段尚未执行；必须先通过本轮并发选档、回退、全新 24 小时试采及原生抽检、独立就绪审计，并在交接时复核原生来源与备份一致。冻结工具不代表上线验收通过。

当前修复针对 ROLLING_BOULDER_POWER 逐次命中千足虫的死亡结算。上一候选 v4 的新教师面板完成 4,540 场，其中 4,539 场匹配、1 场完整终局不一致；控制器与 24 个原生进程已排空，自动验收停止，正式生产未启动。原始成功录像和旧发布均保留。新修复及当前证据见 [逐次死亡结算修复](../../vendor/CombatSolver/coverage/rolling-boulder-hit-order-repair-20261001.json)。

宿主仅恢复原版可见效果逐次调用伤害命令的边界；搜索预测在每次命中后结算死亡能力，并与外层共享已处理死亡集合。千足虫保留已设置的死亡动作，能否重接改读分支中的其他肢节 HP。最小原生完整状态、Fork、存活/死亡和可复活/不可复活边界已通过；诊断宿主对 15 场保留录像的 1,024 个动作点与 15 个终局一致。此项局部回归与上述最终候选的完整验收分别保留。

v4 的 GAMBLING_CHIP 修复、旧录像 10,008 构筑/534,775 动作点回归及单核配对性能均为历史证据。其单核吞吐为 187.73 对 105.21 条/小时，进程树峰值 RSS 中位数为 188.15 对 1587.83 MiB；不能把旧版本的结果转记为新版本已通过。v4 停止详情见 [验证启动清单](gambling-chip-validation-launch-20261001.json)。

2026-10-01 资源实测：整机 256 逻辑核，但 pl 用户组共享 CPU 配额为 32 核；内存硬限制 128 GiB、回收压力阈值 110 GiB。新任务按用户组配额确定并发，产物继续写入空间较充足的 `/data1`。最终 worker 数以 8/16/24/32 的实际吞吐、限流和内存峰值校准决定。

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
