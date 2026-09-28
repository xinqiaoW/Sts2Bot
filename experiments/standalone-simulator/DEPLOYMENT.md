# 独立采集发布目录与回退

最新版正在进行 [万构筑完整状态验收](BUILD_VALIDATION_10000.md)，正式生产会话尚未切换。完整正确性、当前版本性能与并发校准、回退演练、24 小时试采通过后才能切换。

历史发布 `/data1/pl/ImageTask/wxq/Projects/standalone-10000-builds-20260924/terminal-sly-release` 的宿主为 `df11b26d…`。当时的 10,036 构筑、532,666 个动作检查点缺少后来增加的完整终局/出牌区验证，不是当前候选的通过证据。旧发布与原生回退资料继续保留；新候选必须重新冻结产物、教师与来源身份。

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

新库只将原 pending 输入关联到冻结独立教师，保留原构筑、目标、种子、来源窗口、变异谱系和生成序号。原生已完成、失败和隔离输入保存为既有采集记录以防重复调度；原生结果和尝试仍留在原库及快照，不改身份。准备失败时保留临时库，不覆盖重试。此工具不启动采集或切换活动指针，runtime、来源游标、会话和启动核验仍须完成。其 13 项合成数据库测试只验证交接逻辑，不计入实战一致性或长跑数量。

`run_backend_rollback.py` 在隔离实例中演练这一流程：原生队列完成 1 条，切到独立队列并在有效租约期间写入停止标记，排空后备份两库并核对全部尝试，再切回原生完成第 2 条，前后校验发布清单。该演练此前在 2026-09-22 的早期发布上通过；正式切换前应对当前发布重新运行：

```bash
python experiments/standalone-simulator/run_backend_rollback.py \
  --bundle <release-dir> --benchmark <backend-comparison.json> \
  --native-runtime <native-runtime.json> --isolated-native-directory <isolated-dir> \
  --output-root <output-dir> --report <rollback.json>
```
