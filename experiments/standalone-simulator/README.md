# 独立战斗模拟宿主（原型）

**万构筑固定动作差分验收已通过（2026-09-24）**：同一宿主完成 10,036 个不同构筑、532,666 个完整状态检查点，80 个正式目标全部覆盖，未解决差异为 0。同条件实测有效标签吞吐为原生 Wine 采集的 1.924 倍。详见 [万构筑验收](BUILD_VALIDATION_10000.md) 和 [机器可读报告](build-acceptance-20260924.json)。正式生产会话尚未切换，输出仍标记 `productionReady=false` / `productionLabels=false`。

在 Linux 普通 .NET 9 进程中加载已核验的游戏 `sts2.dll` 与 `CombatSolver`，直接执行原游戏的开局、出牌、选择、怪物回合、终局与战后钩子，不启动 Wine/Godot。游戏规则和求解器程序集不做修改；宿主只在临时副本上替换少量编辑器/渲染/平台调用。

## 验收标准

用户确认的正确性标准：**相同初始状态、动作和选择下，完整状态及实际终局标签必须一致**。

- 原生 Wine 游戏实际运行教师并逐动作录制；独立宿主执行相同的动作与选择，不重新搜索。
- 每个命名检查点比较完整状态文本（费用、HP、格挡、能力、全部牌堆及顺序、怪物 AI、遗物状态、RNG），另外比较终局 HP/最大 HP、回合、死亡和净掉血。
- 成功的原生录制不得因回放失败而替换；宿主修改后须重新回放全部成功录制。失败、未完成输入与重复回放都不计数。
- 环境固定为游戏 0.111.0 / 协议 3 / Silent A10、正式教师 Medium short-only、每次搜索 8,000 ms、DOP 1。

两个后端各自限时搜索时可能选出不同路线，因此标签差异只作诊断，不作为规则正确性的门槛。速度对照要求相同任务、种子、教师设置和 CPU 配额，失败与超时计入吞吐分母，交替顺序并重复测量。

## 目录

C# 宿主（`SimulatorPrototype.csproj`，关闭分层编译，避免短时冷搜索主要运行在 tier-0 代码中）：

| 文件 | 作用 |
| --- | --- |
| `Program.cs` | 入口与参数分派 |
| `HostAdapter.cs` | 游戏/求解器 SHA-256 校验；临时游戏副本上的宿主适配；测试存档与进度快照加载 |
| `HostClock.cs`、`NativeDetourHost.cs` | 进程内单调时钟，以及仅限表现层的 Godot 调用替代 |
| `OfflinePlatformService.cs`、`PackedLocalization.cs` | 离线平台身份；从原始 PCK 只读加载英文本地化表 |
| `RequestStartupProbe.cs`、`RequestRestoreProbe.cs` | 按正式请求启动跑局、恢复构筑，并与采集器读回结果比对 |
| `RequestBattleProbe.cs`、`RequestExecution.cs` | 整场战斗与正式请求的结果输出（`StandaloneCompleted`） |
| `TeacherBattleProbe.cs`、`TeacherDeploymentProbe.cs`、`OpeningChoiceSearch.cs` | 原教师搜索、原生部署、路线续接与开局选择 |
| `NativeTraceReplay.cs`、`NativeImplicitChoiceObserver.cs`、`NativePlayerTurnBarrier.cs`、`TerminalCleanupObservation.cs`、`NativeCombatRewards.cs` | 原生录制的固定动作回放、隐式选择、回合边界和终局边界 |
| `RoundProbe.cs`、`OriginalEffectProbe.cs`、`NativeSetupProbe.cs`、`NativeActionProbe.cs`、`FullBattleReplay.cs` | 早期固定用例探针，仍由功能回归执行 |

Python 工具：

| 文件 | 作用 |
| --- | --- |
| `run_probe.py` | 完整功能回归：临时目录构建宿主，运行全部探针、历史请求、原生回放和反例 |
| `run_native_replay_suite.py` | 用已构建宿主回放 `fixtures/native-replay-*.json` 全部固定录制 |
| `run_boundary_negative_suite.py` | 篡改选择、RNG、终局 HP 等 8 个反例，要求全部被拒绝 |
| `prepare_build_panel.py` | 从真实构筑库冻结不同构筑面板（`plan.json` + `cases.sqlite`） |
| `run_build_panel.py` | 在隔离原生 runtime 中录制并用独立宿主回放面板，可续跑 |
| `audit_build_panel.py` | 从原始录制与回放日志独立重新计数并判定是否通过 |
| `build_panel_contract.py` | 构筑去重键、面板校验和万构筑通过门槛 |
| `replay_evidence.py` | 共享的录制/回放完整状态校验与原子写入 |
| `run_backend_comparison.py` | 原生与独立宿主同条件速度对照 |
| `release_tool.py` | 创建、校验、运行冻结发布目录，见 [DEPLOYMENT.md](DEPLOYMENT.md) |
| `run_backend_rollback.py` | 隔离实例中的原生 → 独立 → 原生切换与回退演练 |

`fixtures/`：`restore-1..6.json` 为历史请求及期望结果，`native-replay-*.json` 为原生录制（功能回归与固定回放集使用），`pilot-progress-v24.json` 为冻结的进度快照，`fault-injection-multi-attack.json` 用于部署漂移注入。原生录制 mod 与采集脚本位于 [`../native-trace-probe`](../native-trace-probe/README.md)。

## 宿主命令

```bash
dotnet SimulatorPrototype.dll <game-dir> --execute-request <request.json> [progress.json]
dotnet SimulatorPrototype.dll <game-dir> --replay-native-request <fixture.json> <progress.json>
```

第一种接受 `damage_model.worker.request_for` 生成的正式请求，用原教师执行整场战斗并输出 `StandaloneCompleted`、实际初始构筑、终局观测和独立来源标记。第二种执行原生录制中的动作和选择，并逐点比较完整状态。其余参数（`--battle-request`、`--teacher-battle-probe` 等）只用于回归探针，参见 `Program.cs`。

## 运行

需要 Linux、Python 3、.NET 9 SDK 和已核验的游戏运行目录；不随代码分发游戏 DLL 或资源。可用 `TMPDIR` 把临时构建放到空间充足的磁盘。

完整功能回归（返回 0 表示全部检查通过）：

```bash
python3 experiments/standalone-simulator/run_probe.py \
  --runtime /path/to/game-card-state-v3 --dotnet /path/to/dotnet --report /tmp/functional.json
```

用已构建的宿主运行固定回放集与反例：

```bash
S=experiments/standalone-simulator
python3 $S/run_native_replay_suite.py --host-dll <host.dll> --runtime <game-dir> \
  --progress-snapshot $S/fixtures/pilot-progress-v24.json --dotnet <dotnet> --report /tmp/replays.json
python3 $S/run_boundary_negative_suite.py --host-dll <host.dll> --runtime <game-dir> \
  --progress-snapshot $S/fixtures/pilot-progress-v24.json --dotnet <dotnet> --report /tmp/negative.json
```

万构筑面板：先用 `prepare_build_panel.py --source-root <repo> --source-database <builds.sqlite> --directory <campaign>` 冻结输入；`run_build_panel.py --source-root <repo> --directory <campaign> --setup <setup.json> --host-dll <host.dll> --checkpoint-target 500000` 执行，`setup.json` 列出各隔离 worker 的 native runtime 与录制 mod `traceDll`；排空后运行 `audit_build_panel.py --source-root <repo> --directory <campaign> --plan <campaign>/plan.json --host-dll <host.dll> --output <audit.json>`。运行汇总不能代替独立审计。

速度对照：`run_backend_comparison.py --mode warm-native-batch --cpu <cpu> --repeats 2`，另需隔离实验目录、native runtime、只读历史库、宿主和进度快照。

相关单元测试位于仓库 `tests/`：`test_build_panel_contract.py`、`test_build_panel_audit.py`、`test_native_target_artifacts.py`、`test_raw_completion_contract.py`、`test_native_replay_suite.py`、`test_backend_comparison.py`、`test_standalone_*.py`。

## 边界

- 游戏启用 TestMode，模组初始化为 Skipped，未执行生产中的 Harmony / RitsuLib 启动补丁；存档只写内存。
- 有限面板不能穷尽所有卡牌、遗物与状态组合；验收之外的游戏版本、角色或难度须重新验证。
- 实测倍率仅代表那次同条件对照，不能当作所有任务的固定倍率。
- 最终验收使用的完整源码快照保存在 `/data1/pl/ImageTask/wxq/Projects/standalone-10000-builds-20260924/final-review-source.tar.gz`（清单 `final-review-source-manifest.json`）。开发阶段的中间报告已从仓库移除，原始证据保留在该持久目录。
