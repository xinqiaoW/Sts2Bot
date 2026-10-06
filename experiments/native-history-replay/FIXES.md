# 历史原生回放选牌边界修复（2026-10-06）

修改位于 `codex/standalone-combat-prototype`，验证产物在
`/data1/pl/ImageTask/wxq/Projects/native-history-replay-fixes-20261006`。
正在运行的全量服务继续使用它自己的冻结代码和 DLL。

## 修复

* 开局会话从 `SetupPlayerTurn` 开始，到 `RunAutoPrePlayPhase` 完成才关闭。
  原版后者先等待准备任务，再执行 IMBUED 自动出牌；过早关闭会话会让
  后续的原生选牌失去驱动，并令回合循环故障。
* 最后一个结束回合边界可核销原版终局取消的选择。仅接受已定义的
  未请求计划/页面超时异常，且必须观察到原生终局、回合数与历史一致、
  原生 trace 中未消费的计划数与授权数量一致。终局完整状态仍需严格相等。
* 历史末尾 ENTROPY 变牌账本有一个明确兼容分支：原记录取消数为零，
  但战斗在该结束回合本身结束、最后一项是非空 ENTROPY 变牌计划。
  保留原账本，另记 `legacy_entropy_cleanup`，只容许取消最后一项。
  中间边界、其他来源、其他效果或不同结束回合均不适用。
* 共享测试选牌器在战斗结束后停止依据牌堆推断未观察的选择。
  独立宿主同样保护旧冻结选牌器，避免把清空战斗牌堆误记为变牌已执行。
  已通过原生选择入口消费的计划不受影响。

## 验证

| 原始失败样本 | 原生请求 | 完整状态点 |
|---|---|---:|
| IMBUED / NIGHTMARE：`d3257c83e4f9…` | Passed | 42 |
| 终局 TOASTY_MITTENS：`3b9966fac0ce…` | Passed | 19 |
| 终局 ENTROPY：`3684e63169e0…` | Passed | 21 |

三例按原始保留路线执行，无教师重搜，共 76 次出牌、82 个完整状态点；
包含开局、每次出牌和稳定终局，保留 RNG、有序牌堆及状态文本全部字段。
修改 ENTROPY 样本的终局文本后原生请求明确 Failed，最后检查点标记
`matches=false`，无 `replay_completed`。终局取消不会放过错误终局。

`verify_fixes.py` 从只读失败分析中取每类一个样本，在新建的独立 runtime
执行，并逐项保存原请求、计划、原生结果、日志、检查点和汇总。用法：

```bash
python verify_fixes.py --analysis /absolute/failure-analysis/analysis.json \
  --root /absolute/freshly-prepared-runtime
```

新宿主搭配原冻结教师重跑 ENTROPY 建局，正常变牌仍消费，终局未发生的
选择记为 `consumed=0,cancelledAfterTerminal=1`。这是新搜索路线的账本验证，
不计入上述历史固定路线检查点。

`SelectorAccountingProbe.csproj` 使用新编译的教师，旁观真实原生结束回合：
实际变牌仍能核销；原版终局清空全部牌堆时，旧的变牌推断条件为真，但
新公共核销入口保持未消费。包装器只在独立进程批准明确给定的宿主/教师
哈希，不改变正式宿主的依赖固定值，不推动选择或修改结算。
其参数依次为宿主 DLL、独立游戏目录、请求、进度快照、教师 SHA、宿主 SHA、
全新证据 JSONL。最初包装器的初始化和撤销补丁错误保留在实验目录；
最终证据单独记录，不将这些包装器错误解释为战斗规则差异。

控制器 7 项测试通过；教师、独立宿主、回放 Mod 和核销探针的 Release
构建均零警告/错误，结构门禁通过。单请求上限 120 秒未增加。

初次验证只覆盖三个共享根因的代表及反例。用户随后明确要求验证剩余
45 个同类样本，结果见下节。Wine/Godot 崩溃、菜单清理失败或原生缓存
并发错误仍未标记已修复。
原始隔离 11 个任务的教师预测/计划错误属于另一组问题。

## 剩余 45 个样本完整验证（2026-10-06）

`fix-batches/remaining45` 固定排除了之前原生 Passed 的三个代表。
33 个 IMBUED、7 个 TOASTY_MITTENS、5 个 ENTROPY 样本全部原生 Passed，
无重试。合计 1,025 次出牌、1,115 个完整状态检查点，零状态差异。
验证服务 `sts2-native-history-fixes-45-20261006.service` 正常退出，状态为 success。

逐场原始计划、请求、原生结果、原生日志和检查点全部保留，结果在每场
完成后立即落盘。`audit_fix_batch.py` 另与原始历史计划逐项核对实际状态
文本和哈希，检查动作/选择未改变、请求绑定、终局回合和禁止教师重搜的
完成记录；45 个完整对照全部通过。审计文件位于实验目录
`native/fix-batches/remaining45/audit.json`，结构化记录为
`vendor/CombatSolver/coverage/native-history-replay-remaining45-20261006.json`。

加上前三例，这 48 个同类失败样本均完成原生请求，累计 1,101 次出牌、
1,197 个完整状态检查点一致。此前 86 个失败中的其余 38 个不在此批次。
持续运行的 202,527 场全量服务仍使用自己的旧冻结代码和 DLL。
