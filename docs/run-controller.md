# RunController：真实游戏整局环境

局外规则由原版游戏推进，Python 通过 `runctl.RealRunEnv` 在合法决策点提交动作，每场战斗由 CombatSolver 实际执行。模型全流程策略与启动说明见 [autobot.md](autobot.md) 与 [policy-configuration.md](policy-configuration.md)。已退役的拟合式模拟器保存在[归档目录](历史垃圾箱/sim-v0-fitted/README.md)。

## 能力范围

- 原版 0.111.0，静默猎手，单人标准 A10，完整原生内容解锁与发现，涅奥开局，第一幕按原版 `act_selection` 随机流选择。
- 沿用整局实际生命值、牌组、遗物、计数及升级（A10 正常起手为 56/70，不套用单场采集的 70/70 标准化）。
- 支持两种 `decisionMode`：
  - `all`（CLI `--policy model` 默认）：导出所有已适配局外界面（`MAP`、`EVENT`、`SHOP`、`REST`、`TREASURE`、`REWARDS`、`CARD_REWARD`、`CHOOSE_CARD`、`RELIC`、`BUNDLE`、`CARD_GRID`、`CRYSTAL`），由 Python 策略决策。
  - `map`（CLI `--policy random-map` 基线）：仅导出 `MAP` 路线选择；事件逐项随机选择，奖励、选牌、商店、篝火、宝箱使用原版 AutoSlay 的局外处理器。
- 支持两种战斗搜索模式（`combat_search_mode`）：
  - `evaluation8s`（默认）：固定 Medium、8 秒短搜、DOP 1、禁用药水、关闭 No-GC、Instant 部署；单场上限 120 秒，整局默认 3600 秒，单次决策上限 300 秒。
  - `settings`：读取独立游戏存档内的 CombatSolver 搜索设置；单场默认 1800 秒（上限 3600 秒），整局默认 14400 秒，单次决策默认 1800 秒（上限 3600 秒）。
- `runctl.RealRunEnv` 提供同步 `reset/step/close`，不提供 F 跳战。

## 所有权与隔离

内嵌求解器的 `vendor/CombatSolver/src/Testing/UnattendedTestRunner.ProtocolHost.cs` 独占游戏请求邮箱及进程复用；`vendor/CombatSolver/src/RunControl/RunControlSession*` 拥有单局状态、原生交互、决策序号及日志；同目录的 `RunControlProtocol.cs` 拥有协议校验和文件写入。

只有环境变量 `COMBATSOLVER_RUN_CONTROL=1` 的独立进程才能接受整局请求，Python 配置还必须声明 `kind: "run_control"`。一个环境独占一个用户目录和进程；失败后退出该进程，保留原始尝试，下一次调用使用新的 run ID。自然死亡或通关是完成的对局，超时和异常是失败。

## 原生接入约束

1. **禁止调用 AutoSlayer 战斗作弊处理器。** 原版普通/事件战斗处理器会施加 999 层能力或直接杀死敌人。整局控制器仅使用 CombatSolver 执行真实战斗，不调用 `AutoSlayer.Start`。
2. **启用完整内容解锁与发现。** 在独立进程创建跑局期间通过 `RunControlUnlockScope` 启用完整内容，避免新存档进入首次教学流程或缺失遭遇/遗物池。
3. **界面栈与嵌套选择。** 地图已打开时优先处理可旅行地图；购买、事件和篝火触发子选牌界面时，在父操作等待期间导出并处理子界面，未知界面或反复停滞明确报错。

## 协议 v1

整局请求复用 `user://combat_solver_test_request.json` 邮箱，以 `kind: "run"` 分流：

```json
{"schemaVersion":1,"kind":"run","runId":"unique-id","seed":"RUNCTL0","characterId":"SILENT","ascension":10,"combatMode":"solver","decisionMode":"all","policySeed":0,"timeoutSeconds":3600,"actionTimeoutSeconds":300,"combatTimeoutSeconds":120}
```

原生接受后，每局文件位于 `user://combat_solver_runs/<runId>/`：

| 文件 | 含义 |
| --- | --- |
| `accepted.json` | 经校验的请求；同一 ID 只能接受一次 |
| `decision.json` | 当前界面（`screen`）、合法候选项（`options`）、角色与地图状态（`state`）及递增 `decisionSeq` |
| `action.json` | Python 的原子写入；原生消费后转存为 `action-00001.json` 等 |
| `events.jsonl` | 带递增事件序号的追加日志，含战前/战后、楼层、事件选择及局外操作前后状态 |
| `native-run.json` | 终局原生 `RunManager.ToSave` 快照，含原生逐层历史 |
| `result.json` | 自然死亡/胜利且清理完成后才写 `complete`；异常写 `failed` 与阶段和错误 |

动作格式：

```json
{"schemaVersion":1,"runId":"unique-id","decisionSeq":1,"choice":0}
```

动作必须包含全部字段，匹配当前 `runId` 与 `decisionSeq`，且 `choice` 为合法选项下标。

## 使用与数据边界

命令与独立环境配置见 [runctl/README.md](../runctl/README.md)，早期 M1 协议验收记录见[原生验收](run-controller-validation.md)。整局日志单独存储，其输入生命值、遗物和内容池不同于 70/70 标准化单场采集，不能直接写入单场 F 训练库。F 跳战未接入：平均掉血和死亡概率不能单独确定最大生命、遗物回合计数、永久牌组变化与奖励结算。
