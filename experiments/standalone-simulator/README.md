# 独立战斗模拟原型（实验，不能用于采集）

在 Linux 普通 .NET 9 进程中复用现有 CombatSolver，完成固定测试状态的根捕获、分叉、出牌、怪物行动、回合推进和终局判断，不启动 Wine/Godot 游戏进程。

**当前通过小型人工状态的胜负用例与三个原游戏效果的对照，尚未接真实构筑、43 个编组或正式教师搜索。不能生成训练标签。**

## 运行

需要 Python 3（Linux）、.NET 9 SDK 和已有游戏运行目录。不随代码分发游戏 DLL 或资源。

```bash
python3 experiments/standalone-simulator/run_probe.py \
  --runtime /data2/pl/ImageTask/wxq/Projects/Sts2Bot/.runtime/game-card-state-v3 \
  --dotnet /data2/pl/ImageTask/wxq/Projects/dotnet/dotnet \
  --report /tmp/standalone-simulator-report.json
```

可通过 `TMPDIR` 将临时构建目录放到有空间的实验磁盘。脚本复制源文件到临时目录构建，依次启动单个实验进程，设置 `DOTNET_PROCESSOR_COUNT=1`（线程提示，不是 CPU 硬配额）。构建限时 60 秒，各进程限时 30 秒，关闭 core dump，结束后清理临时目录。

脚本返回 0 表示所有当前实验检查通过。`productionReady` / `productionLabels` 仍为 false。没有队列导入、数据库、运行锁或生产任务操作。

## 代码边界

- `HostAdapter.cs`：校验游戏及求解器 SHA-256；游戏 DLL 仅在临时副本中适配三处宿主方法：编辑器检测、原生控制台输出、离线平台构造。第三项保留离线 ID 1 和原有名称回退，只取消可选的 mp_names.json / Godot 文件读取。日志仍通过 LogCallback 输出；原始游戏与求解器 DLL 不变。
- 游戏启用 TestMode，使用原始角色、模型、RNG 和 RunState.CreateForTest。存档服务仍只挂载真实 Progress，其他服务不可用；模组初始化为 Skipped，未执行生产中的 Harmony / RitsuLib 启动补丁。这些是局部测试环境约束，不是通用游戏宿主。
- `OfflinePlatformService.cs`：只提供明确的离线 Platform.None；其他网络调用立即报错。
- `PackedLocalization.cs`：按 [Godot 4.5 官方 PCK 读取实现](https://github.com/godotengine/godot/blob/4.5/core/io/file_access_pack.cpp) 描述的布局，只读取原始游戏包里的 46 份英文 JSON 表（约 600 KiB），校验各文件 MD5，并使用原游戏的 LocTable 和 SmartFormat。不会整包解压，也不伪造缺失文本；仅支持已核验的非加密 PCK v3 / Godot 4.5.1。
- `Program.cs`：建立人工状态，初始化原游戏怪物状态机，调用原有 CombatRootSnapshot.Capture。原有捕获前后稳定性与投影一致性检查仍执行。
- `RoundProbe.cs`：正常构造原有 CombatBeamSolver，通过版本固定的反射入口复用 AdvanceRound；没有重写回合规则。以“按手牌顺序打出合法打击/防御”作为固定测试动作，不运行搜索。未知牌、待选择项、预测风险或非 None 边界立即失败；最多 40 回合、每回合 20 次出牌。
- `OriginalEffectProbe.cs`：调用原游戏的 StrikeSilent/DefendSilent.OnPlay 与 Chomper.ClampMove，和镜像模拟做效果对照。用原游戏 CombatTurnState 把人工状态标为进行中，避免原效果因战斗未开始而被跳过；没有执行完整游戏启动或战斗开始流程。

## 已验证的范围

`evidence/phase2-20260921.json` 是当前报告，包含 DLL 指纹、检查结果和逐动作完整 ContinuationStamp；`evidence/probe-20260921.json` 保留第一版的有限冒烟结果。

| 检查 | 结果 |
| --- | --- |
| 基础模拟器与影子根分叉，各重复 1,000 组打击/防御 | 通过 |
| CombatRootSnapshot 原有稳定性与投影一致性校验 | 通过 |
| 64 HP Chomper，70 HP Silent，人工两张牌状态 | 第 9 回合玩家死亡，敌人剩 28 HP |
| 相同人工状态，但敌人初始生命设为 12 | 第 2 回合获胜，玩家剩 59 HP |
| 上述胜负用例各运行两次，比较逐动作完整状态文本 | 全部一致，共 4 次人工战斗回放 |
| 回放前后重新分叉根并比较完整状态文本 | 根未被回放改写 |
| 原游戏打击、防御、Chomper 两次攻击效果对照 | 敌人 64→58；格挡 0→5；玩家 70→59、格挡归零，均一致 |
| 不匹配的游戏/求解器版本 | 拒绝运行 |

两组终局回放各包含两次战斗，计时分别约 0.19 秒和 0.17 秒。计时含首次方法 JIT、状态序列化和断言，不含进程启动、根捕获或教师搜索。这只是小型用例的执行时间，不能换算成真实构筑的每小时场数，也不是相对正式采集的加速倍数。

原始对象保护的两张牌冒烟检查比较生命、格挡、能量、五个牌堆的卡牌 ID 顺序、能力 ID/层数和运行 RNG。完整回放的分叉检查使用既有 ContinuationStamp，包含模型、牌堆、怪物状态与 RNG 等状态。

## 尚未验证

这里是手工构造的测试战斗，不是自然开局：手牌只有两张基础牌，未执行开局抽牌、遭遇编组初始化与战斗开始钩子，例如 Chomper 的初始 Artifact 没有自动注入；胜利用例还主动降低了敌人生命。终局仅指模拟器中的胜负边界，不包括战斗后奖励和房间退出。

原游戏效果对照不覆盖出牌包装流程、能量支付、牌堆迁移、原生回合推进或完整游戏宿主。重复模拟一致也不等价于与原生整场一致。

下一步应实现真实构筑与遭遇的完整初始化，选取代表性案例，逐动作对照原生游戏的 HP/格挡/能力、牌堆顺序、怪物 AI、RNG 与最终结算。完成后才能接入原教师的 8 秒搜索，并测真实场次吞吐和标签质量。若改变搜索预算，需要单独评估标签影响；本原型未修改正式教师、补采逻辑或生产数据。
