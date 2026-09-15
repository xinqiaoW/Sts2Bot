# RunController：用真实游戏做 RL 环境（路 B）

2026-09-15 决定。放弃拟合式抽象模拟器（已移入 [历史垃圾箱](历史垃圾箱/sim-v0-fitted/README.md)），改为让原版游戏进程本身充当环境：所有局外规则（地图、遭遇池、奖励、商店、篝火、事件、上古、遗物效果）由游戏原样执行，Python 只负责在决策点给出动作。战斗可由 CombatSolver 全自动打，也可以在需要提速时用训练好的期望掉血模型 F 直接结算并跳过。

## 已确认的事实（来源：`decompiled/` 与 `vendor/CombatSolver`）

- 原版内置 `MegaCrit.Sts2.Core.AutoSlay.AutoSlayer`：官方冒烟测试机器人，已经覆盖整局流程——主菜单开局、每种房间（`CombatRoomHandler`/`EventRoomHandler`/`ShopRoomHandler`/`TreasureRoomHandler`/`RestSiteRoomHandler`）和每种覆盖层（奖励、选卡、升级/转化/附魔/删卡、选遗物、选包、水晶球、游戏结束）。它用 `Rng` 随机做每个选择。发布版把 `--autoslay` 命令行关掉了（`NGame.IsReleaseGame()` 恒为 true），但这些类是 public 的，mod 里可以直接实例化或照抄。它就是 RunController 的现成骨架：把每个 `random.NextItem(...)` 换成"把候选列表发给 Python，等动作"。
- 局外操作有非 UI 入口：`RunManager.Instance.EnterMapCoord(coord)`（地图移动）、`RunState.Map.GetPoint / MapPoint.Children`（可达节点）、`StartNewSingleplayerRun(character, shouldSave, acts, modifiers, seed, GameMode, ascension)`（我们采集器已在用）、`RunManager.Abandon()`。奖励、商店、篝火、事件在 AutoSlay 里走的是 UI 节点点击（`UiHelper.Click`），无头模式下可用（AutoSlay 本身就是无头跑的）。
- 跳过战斗的原语：`CreatureCmd.SetCurrentHp(player.Creature, hp)` + `CreatureCmd.Kill(enemies, force: true)`。战斗以胜利结束后奖励屏由游戏正常生成，不需要我们伪造奖励。
- 现有 IPC：CombatSolver 无人协议已经是"Python 写 `user://combat_solver_test_request.json` → mod 轮询（每 10 帧）→ 写 `result.json`"，`damage_model/worker.py` 负责进程复用、超时和原生故障分类。RunController 沿用同一套进程管理与故障隔离，只是把一次请求从"一场战斗"扩展成"一整局 + 多轮决策往返"。
- 每个 Wine worker 一个独立 prefix，25 路已在跑。RL 环境天然按 worker 向量化。

## 架构

```
Python                                   游戏进程 (Wine headless, 每 worker 一个)
──────────────────────────────           ─────────────────────────────────────────
runctl.env.RealRunEnv (gym 风格)  <────>  CombatSolver.dll 内新增 RunController
  reset(seed, character, ascension)       - StartNewSingleplayerRun
  step(action)                            - 主循环：AutoSlayer 流程，但每个决策点
  obs = 决策点 JSON                           写 decision.json 后阻塞等待 action.json
runctl.oracle (F 集成，跳过战斗)           - 战斗：solver 全自动 / skip(F)
runctl.pool (复用 worker 池)              - 终局：写 run_result.json（含完整 .run 等价历史）
```

放在 vendored CombatSolver 同一个 DLL 里（新目录 `src/RunControl/`），不另起 mod：真战斗要调用 CombatSolver 的全自动执行器，无头启动、进程复用、FTUE 禁用、Fast 模式这些已经在 `UnattendedTestRunner` 里调通了。`RunController` 是无人协议的一种新请求类型（`SchemaVersion` 提升，`Kind = "run"`），不改动现有训练采集路径。

### 协议（文件，同现有目录）

一次请求对应一整局：

```jsonc
// run_request.json  (Python → mod)
{"schemaVersion": 2, "kind": "run", "runId": "...", "characterId": "SILENT", "ascension": 10,
 "seed": "ABC123", "combatMode": "solver" | "skip" | "auto", "timeoutSeconds": 3600}
```

局内每个决策点，mod 写 `decision.json` 并等待 `action.json`（按 `decisionSeq` 匹配，防串位）：

```jsonc
// decision.json (mod → Python)
{"runId": "...", "decisionSeq": 17,
 "screen": "MAP" | "CARD_REWARD" | "REWARDS" | "SHOP" | "REST" | "EVENT" | "BOSS_RELIC" |
           "TREASURE" | "DECK_SELECT" | "ANCIENT" | "COMBAT_ENTRY" | "GAME_OVER",
 "state": {"act": 1, "actFloor": 6, "totalFloor": 6, "hp": 52, "maxHp": 70, "gold": 143,
           "deck": [{"id": "STRIKE_SILENT", "upgrade": 0, "state": {...}}, ...],
           "relics": [{"id": "...", "state": {...}}], "potions": [...],
           "map": {...可达节点与整张图...}, "currentCoord": [row, col]},
 "options": [ {"index": 0, "kind": "card", "id": "BACKFLIP", "upgrade": 0},
              {"index": 1, "kind": "skip"} , ... ],
 "context": {"encounterId": "...", "roomType": "MONSTER", "eventId": "...", "prices": [...]} }
```

```jsonc
// action.json (Python → mod)
{"runId": "...", "decisionSeq": 17, "choice": 0,
 "combat": {"mode": "skip", "hpAfter": 45, "maxHpAfter": 70} }   // 仅 COMBAT_ENTRY
```

候选列表由 mod 从游戏对象直接枚举（`NCardHolder`、`NRewardButton`、`NMerchantSlot`、`NRestSiteButton`、`NEventOptionButton.Option`、`NMapPoint.Point.Children`），Python 永远只在合法动作里选；非法索引由 mod 直接报错终止该局（同 CombatSolver 的"未知语义显式失败"原则）。

终局 `run_result.json` 写完整逐层历史（房间、遭遇、HP/金币前后、选项、战斗模式与是否被跳过），字段对齐 `.run`，便于沿用 `sim/history.py` 的展平逻辑做真人对比。

### 战斗的三种模式

| 模式 | 做法 | 用途 |
| --- | --- | --- |
| `solver` | CombatSolver 全自动（8 秒预设、无药水，与现有标签老师一致） | 真值；每场顺带产出一条新的 F 标签（闭环数据） |
| `skip` | 进入战斗、发牌稳定后，mod 上报 `COMBAT_ENTRY`（战前构筑 + 遭遇）；Python 用 F 集成采样掉血/死亡，回传 `hpAfter`；mod 设 HP、强杀全部敌人，进入正常奖励流程 | 提速 |
| `auto` | Python 按规则决定：F 有覆盖且集成方差小 → skip；精英/Boss、无覆盖目标、或卡组含战斗内副作用的牌/遗物 → solver | 默认 |

`skip` 会丢掉战斗内副作用，必须显式处理而不是忽略：

- 回合数/击杀相关计数遗物、战斗中永久变化（吸血/进食类加上限、Lesson Learned 类升级、诅咒/状态牌的战后增减、药水消耗）——`auto` 模式对这些构筑强制 `solver`。名单从 `damage_model/catalog.py` 的排除表和 `docs/relic-rules.md` 出发，运行中遇到未列出的战后 diff（mod 比对战前/战后卡组与遗物状态）就报错，而不是静默继续。
- F 的偏差在真人卡组上约 +0.46 HP（`sim-v0-fitted` 报告）；RL 策略走出真人分布后偏差未知，所以 `auto` 模式的 skip 比例要能按训练阶段收紧，且每个 epoch 固定抽一部分 skip 场次改用 `solver` 复测，监控偏差漂移。

### Python 侧

- `runctl/env.py`：`RealRunEnv`，`reset()` 发 `run_request`，`step()` 写 action、等下一个 decision；`VecRealRunEnv` 持有 N 个 worker 进程（复用 `damage_model/worker.py` 的启动、复用、故障分类与隔离逻辑）。
- 观测编码复用 `train/features.py` 的卡牌/遗物词表；策略是"给候选打分"的 pointer 结构（每个 option 一个 logit），天然处理变长动作集。
- 先用真人 `.run` 做行为克隆（选项 = 真人当时的候选，`sim/history.py` 的展平逻辑可回收），再 PPO 微调；奖励 = 通关 + 少量存活层数 shaping。
- 同一 seed 下不同策略可做配对比较（游戏 RNG 由 seed 决定），评估方差远小于随机 seed。

## 吞吐估计（需实测，先按下面假设排期）

- 一局约 50 层、30 场战斗。`solver` 模式下一场 1–3 分钟（8 秒短搜 × 若干回合），整局 30–60 分钟/worker；25 路约 30–50 局/小时。
- `auto` 模式若普通战斗 80% 被跳过，只有精英/Boss 与少数构筑走 solver：整局约 5–10 分钟，25 路约 150–300 局/小时。
- PPO 对样本量的需求可用 BC 起点和配对 seed 评估来压低；真正的瓶颈是 worker 数与内存（现有 25 路配置已知稳定）。

## 分阶段

1. **M1 打通**：mod 新增 `run` 请求；开局 → 上报 `MAP` 决策 → Python 随机选 → `EnterMapCoord` → 房间由 AutoSlay 原逻辑随机处理 → 终局写 `run_result.json`。单 worker、无头、`solver` 模式。验收：连续 20 局无挂起，逐层记录与游戏日志一致。
2. **M2 全决策点**：把 AutoSlay 各 handler 的随机选择全部换成决策上报（含 Neow/上古、事件的多步选项、商店多次购买、篝火、宝箱、Boss 遗物、各种选卡屏）。加 `skip` 模式与战后 diff 校验。验收：随机策略 100 局，决策类型覆盖真人 `.run` 里出现过的所有 screen。
3. **M3 训练**：`runctl` 环境与 25 路池；BC 数据集与训练；PPO；配对 seed 评估对比随机/启发式/BC/PPO。
4. **M4 闭环**：solver 场次回灌 F 标签库；定期用新 F 重新校准 skip 偏差。

## 已知风险

- Wine 无头下的 UI 点击路径（奖励、商店、事件）比直接 API 更脆；AutoSlay 已用同样方式跑通，但个别事件有自定义屏（水晶球等），未覆盖的屏按"显式失败 + 隔离该局"处理，不允许猜测。
- 一局运行时间长，单次原生崩溃会丢整局；沿用现有 `retry_then_quarantine` 分类，但按局而不是按场重试，并保留已完成的逐层记录用于 BC。
- 现有 vendored CombatSolver 的 `AGENTS.md` 限定该 mod 只做战斗；RunController 放在其中是为了复用执行器与进程管理，改动必须限于新增 `src/RunControl/` 与协议分发，不触碰搜索语义。
