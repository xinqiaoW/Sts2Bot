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

1. 保存原生会话、三队列、教师清单、runtime、来源游标和活动指针的一致备份。先停止原生控制器，再排空其池和在途战斗。
2. 独立后端使用自己的队列和冻结教师身份；不改写原生历史 attempts、不把 `StandaloneCompleted` 改为 `Passed`，也不在两种教师之间直接改队列身份。
3. 切换前确认控制器/池/worker 锁均已释放，running=0，旧实例的停止原因已处理；原生回退资料和已验证发布目录都保留。
4. 如需回退，先停止并排空独立实例、保存其全部尝试和备份，再恢复原生活动指针/会话及原生 runtime。有效租约不抢占，过期租约走已有恢复路径。

`run_backend_rollback.py` 在隔离实例中演练这一流程：原生队列完成 1 条，切到独立队列并在有效租约期间写入停止标记，排空后备份两库并核对全部尝试，再切回原生完成第 2 条，前后校验发布清单。该演练此前在 2026-09-22 的早期发布上通过；正式切换前应对当前发布重新运行：

```bash
python experiments/standalone-simulator/run_backend_rollback.py \
  --bundle <release-dir> --benchmark <backend-comparison.json> \
  --native-runtime <native-runtime.json> --isolated-native-directory <isolated-dir> \
  --output-root <output-dir> --report <rollback.json>
```
