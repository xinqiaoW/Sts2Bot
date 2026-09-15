# RunController：真实游戏整局环境

当前工作分支：`feat/rl-combat-env`。局外规则由原版游戏执行，Python 在地图决策点选择合法路线；每场战斗由 CombatSolver 实际执行。旧拟合式模拟器保存在[历史目录](历史垃圾箱/sim-v0-fitted/README.md)。

## 第一版范围

- 原版 0.111.0，静默猎手，单人标准 A10，完整原生内容解锁，捏奥开局。
- 沿用整局实际生命值、牌组、遗物、计数及升级。A10 正常起手为 56/70，不套用独立战斗采集的 70/70 标准化。
- Python 接管地图合法选项；事件由整局控制器逐项随机选择，奖励、选牌、商店、篝火、宝箱使用原版 AutoSlay 的局外处理器。后者是固定基线，有些行为是拿取所有奖励或购买所有可负担物品，并非所有选项均匀随机。
- 普通、精英、Boss 及事件内战斗均使用 CombatSolver：Medium、8 秒短搜、DOP 1、禁用药水、关闭 No-GC、Instant 部署。单场上限 120 秒，整局上限默认 3600 秒。
- 原生奖励仍可能产生药水，库存照实记录，战斗基线不使用药水。
- `runctl.RealRunEnv` 提供同步 `reset/step/close`。第一版不是完整 Gym/PPO 接口，不提供 F 跳战或整局向量池。

## 所有权与隔离

`src/Testing/UnattendedTestRunner.ProtocolHost.cs` 仍独占游戏请求邮箱及进程复用；`src/RunControl/RunControlSession*` 拥有单局状态、原生交互、决策序号及日志；`RunControlProtocol.cs` 拥有协议校验和文件写入。Search、Mirror、评分及出牌政策保持原有职责。

只有环境变量 `COMBATSOLVER_RUN_CONTROL=1` 的独立进程才能接受整局请求。Python 配置还必须明确 `kind: run_control`。一个环境独占一个用户目录和进程；失败后退出该进程，保留原始尝试，下一次调用使用新的 run ID。自然死亡是完成的对局，超时和异常是失败。

生产采集继续使用 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot`；整局试验使用相邻的 `Sts2Bot-runctl-pilot` 独立游戏副本和 Wine prefix。开发仓库的 DLL 只部署到试验副本，不能直接覆盖生产采集器。

## 已纠正的设计假设

1. **AutoSlayer 整体不是正常玩法。** 原版普通战斗处理器会施加 999 层防御/再生能力；事件战斗处理器还会施加能力、移除敌方阻止战斗结束的能力并杀死敌人。整局控制器不调用这两个处理器，也不调用会结束整个进程的 `AutoSlayer.Start`。
2. **全新采集存档缺少内容解锁。** 不解锁捏奥时原版会走首次游玩流程，初始层与 A10 开局效果不同。整局请求在独立进程内通过原生 Epoch 接口启用完整内容，再由游戏创建跑局。
3. **地图和奖励界面可同时留在界面栈里。** 地图已经打开时优先处理可旅行地图，避免对已完成的奖励界面重复点击。
4. **购买、事件和篝火可能等待嵌套选牌界面。** 控制器在父操作等待期间处理子界面，原生操作自己完成结算。未知界面和反复不推进的操作明确失败。
5. **反编译目录是参考资料。** 编译以试验游戏副本所用程序集为准；现有参考目录与冻结程序集的 AutoSlay 商店构造参数存在差异，不能只凭参考文本判断可直接调用。

## 协议 v1

整局请求复用 `user://combat_solver_test_request.json` 邮箱，以 `kind: run` 分流。单场无人请求版本及训练观察版本保持各自定义，不能混为一个 schema。

```json
{"schemaVersion":1,"kind":"run","runId":"unique-id","seed":"RUNCTL0","characterId":"SILENT","ascension":10,"combatMode":"solver","policySeed":0,"timeoutSeconds":3600,"actionTimeoutSeconds":60,"combatTimeoutSeconds":120}
```

原生接受后，每局文件位于 `user://combat_solver_runs/<runId>/`：

| 文件 | 含义 |
| --- | --- |
| `accepted.json` | 经校验的请求；同一 ID 只能接受一次 |
| `decision.json` | 当前地图决策、可选位置、角色状态与递增 `decisionSeq` |
| `action.json` | Python 的原子写入；原生消费后转存为 `action-00001.json` 等 |
| `events.jsonl` | 带递增事件序号的追加日志，含战前/战后、楼层、事件选择及局外操作前后状态 |
| `native-run.json` | 终局原生 `RunManager.ToSave` 快照，含原生逐层历史；不是 Spire Codex `.run` 导入接口 |
| `result.json` | 自然死亡/胜利且清理完成后才写 `complete`；异常写 `failed` 与阶段和错误 |

```json
{"schemaVersion":1,"runId":"unique-id","decisionSeq":1,"choice":0}
```

动作必须包含全部字段，匹配当前 run ID 与决策序号，选项仍须通过原生合法性检查。旧动作、重复动作、缺字段和越界输入不能被当作默认选项执行。

状态保存逐张卡牌的 ID、升级、原生附魔与持久字段；遗物保存原生状态，包括计数。原生选择界面目前记录处理前后状态与界面类型，尚不对所有界面导出完整候选集合，因此这些记录不能宣称是完整行为克隆数据集。

## 使用和验收

命令与独立环境配置见 [runctl/README.md](../runctl/README.md)，实测结果见[原生验收](run-controller-validation.md)。协议测试覆盖进程复用、ID/序号隔离、非法动作、失败结果、独占锁和超时保留现场。原生测试按开局、战斗、奖励、连续楼层、终局、同进程下一局逐步进行；验收场次和实际覆盖以运行报告为准。

整局日志单独存储。其输入生命值、遗物和内容池不同于标准化战斗采集，不能直接写入现有 F 训练库。

## 后续阶段

1. 将事件、商店、篝火、奖励及各类选牌的完整合法候选统一交给 Python；补齐截断、奖励与批量环境接口。
2. 实现经过校验的 F 结算。强杀敌人可能触发爆炸、复活或遗物；单独预测平均掉血及死亡概率也不足以得到一致的结算分布。需要处理当前血量、最大生命、回合计数、战斗内永久变化与奖励边界，并用原生对战逐项验证。
3. 在数据支持完整候选时进行行为克隆，再接入强化学习；吞吐、胜率和 F 分布外偏差都应实测。
