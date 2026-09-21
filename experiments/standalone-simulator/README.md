# 独立战斗模拟原型（实验，不能用于采集）

此目录验证：能否在 Linux 普通 .NET 9 进程中调用现有 CombatSolver 的模拟内核，不启动 Wine / Godot 游戏进程。

**当前只通过固定两张牌的冒烟检查，尚未实现完整战斗、搜索或生产数据导入。完整战斗数为 0。**

## 运行

需要 Python 3（Linux）、.NET 9 SDK 和本地已有的游戏运行目录；不随代码分发游戏程序集。

```bash
python3 experiments/standalone-simulator/run_probe.py \
  --runtime /data2/pl/ImageTask/wxq/Projects/Sts2Bot/.runtime/game-card-state-v3 \
  --dotnet /data2/pl/ImageTask/wxq/Projects/dotnet/dotnet \
  --report /tmp/standalone-simulator-report.json
```

脚本复制三份源文件到临时目录编译。仅启动一个实验进程，设置 `DOTNET_PROCESSOR_COUNT=1`；构建限时 60 秒，各运行限时 30 秒，禁用 core dump，结束后清理临时目录。这里的线程提示不等于 CPU 硬配额。

不会访问补采队列、训练标签、运行锁、生产进程或定时任务。报告通过临时文件校验后原子替换。输出中的 `productionReady` / `productionLabels` 始终为 false。

## 实现与范围

- `HostAdapter.cs`：对指定 SHA-256 的游戏 DLL 创建临时副本，只改两个日志宿主方法（编辑器检测与原生控制台打印）。日志仍通过 `LogCallback` 输出。原始 DLL 与 CombatSolver DLL 均不修改；未知版本拒绝运行。
- 启用原游戏 `TestMode`，用原始模型、角色和 `RunState.CreateForTest` 建立固定测试状态。
- 原游戏存档初始化会触发依赖 Godot `StringName` 的按键设置迁移。原型通过游戏的 `MockInstanceForTesting` 接口挂载仅具备 `Progress` 的测试存档对象：使用未执行构造函数的 SaveManager/ProgressSaveManager，其余服务不可用。这是局部实验适配，不能作为完整运行环境或通用存档实现。
- 原型把模组加载状态设为 Skipped，不执行生产中的 Harmony / RitsuLib 启动补丁。因此本测试环境不能视为与正式 runtime 等价。
- `Program.cs`：手工准备 Silent 的 StrikeSilent、DefendSilent 和 3 点能量，对单只 Chomper 调用原有 `CombatPredictionSimulator.ManualPlay`。没有手写替代伤害公式，也没有修改 vendor 源码。
- 普通模式使用基础 CombatState，仅验证两次出牌；完整可分叉的 SimulatedCombatState 另开进程诊断，失败就保留异常，不回退为伪造战斗结果。

## 已验证

`evidence/probe-20260921.json` 是可复现的实测报告，包含 DLL 指纹、阶段、异常和计时。

固定用例检查敌人生命 64 → 58、玩家格挡 5、剩余能量 1、空手牌，以及弃牌顺序 STRIKE_SILENT → DEFEND_SILENT。重复 1,000 次，每次重建基础模拟器。

同时比较原对象的生命、格挡、能量、五个牌堆的卡牌 ID 顺序、能力 ID/层数和运行 RNG 序列化状态，确认这些字段未被模拟改写。此检查不涵盖全部内部字段，也不代表怪物 AI、洗牌、遗物或整场战斗等价性。

这是针对明确预期值的冒烟检查，**没有与原生游戏逐动作做差分验证**。冷启动和首次 JIT 不计入内部循环计时；循环包含模拟器创建、两次出牌、断言和上述状态快照。实测约 0.5 秒完成 2,000 次简单出牌，进程峰值工作集约 120 MiB。该数字不能换算成每小时完整战斗数，也不是相对生产采集的加速倍数。

未知程序集的拒绝检查也包含在报告中。脚本返回 0 只表示固定用例与版本拒绝检查通过，不表示完整快照或生产采集通过。

## 当前阻塞与下一步

完整 `SimulatedCombatState` 捕获在读取玩家相关环境时抛出 NullReferenceException。结合对应源码，捕获依赖 `RunManager.Instance.NetService.Platform` 等平台信息。直接创建原生单人网络服务还会触发版本信息的原生宿主依赖。原型没有通过伪造任意默认值来继续这条路径。

后续需要先提供明确的无界面宿主边界（存档、平台身份、初始化），然后完成真实构筑的初始化、初始牌序和 RNG、怪物 AI、回合推进及选择分支。用原生游戏对照生命/格挡/能力、牌堆顺序、怪物状态、RNG 和最终结算，确认一致后才能接教师搜索并测完整战斗吞吐。

现有教师的 8 秒搜索预算仍然独立存在。去除游戏宿主不保证同比降低搜索耗时；若改变预算或搜索策略，必须重新评估标签质量。这个原型不会调整正式教师，也不会把实验结果写回补采库。
