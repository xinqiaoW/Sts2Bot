# 模型驱动整局机器人（开发中）

原版单人静默猎手 A10，CombatSolver 执行战斗，Python 处理地图、事件、奖励、卡牌、遗物、商店、篝火、宝箱及嵌套选择。当前正在流程诊断，尚未完成 100 局评测或 Windows 验收；见 [开发进度](autobot-progress.md)。

## 参数和选牌门槛

统一参数在 [bot-policy.json](../configs/bot-policy.json)，底层 rollout 参数沿用 [reward-policy.json](../configs/reward-policy.json)。修改后重启机器人进程。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `short_weight` / `long_weight` | 0.35 / 0.65 | 短期与长期权重 |
| `normal_card_min_gain` | 1 | 正常加牌必须严格超过跳过分加此值 |
| `crisis_card_min_gain` | 0 | 艰难局面仍要求加牌优于跳过 |
| `crisis_boss_loss_fraction` | 0.8 | 正常 rollout 最佳长期预期损失达到最大 HP 的此比例则扩大搜索；不是死亡概率 |
| `crisis_samples_per_parent` | 96 | 艰难局面每个父节点抽样数 |
| `crisis_keep_per_parent` | 6 | 艰难局面每个父节点保留数 |
| `crisis_extra_depth` / `max_rollout_depth` | 1 / 4 | 深度增量和上限，同时受剩余楼层约束 |
| `gold_hp_value` / `shop_reserve_gold` | 0.04 / 50 | 金币代价与保留金币 |
| `rest_hp_fraction` | 0.55 | 篝火回血 HP 风险阈值 |
| `route_beam_width` / `route_risk_weight` | 64 / 2 | 地图路径保留宽度与低血量代价 |

分数越大越好。例如跳过 -20：卡牌 -19 时跳过，-18.99 才允许拿牌。可放弃的奖励、事件加牌、商店均执行门槛；商店另扣价格代价。强制选牌不伪造跳过，免费回血、升级、删牌不套用加牌的 +1 门槛。

普通 rollout 每个父节点保留 4 个分支，深度 n 对应每个初始候选 4^n 个末端节点；艰难局面默认 6^n。白/蓝/金抽样比 9:5:1。日志保存分数、跳过分、风险状态、深度、实际分支统计及门槛排除项。

## 信息和模型边界

- 使用公开地图、可见 Boss 和公开遭遇分布；前几场弱怪根据已打过的普通房间数量推断，不读取下一只怪。
- 不导出未知房具体事件、未点开的卡牌奖励、水晶球隐藏结果或游戏 RNG。
- 模型拒绝的遗物从评分输入排除并记录，真实库存保留。遗物主要比较即时战损。超出训练范围的卡牌和牌组投影/外推也会记录。
- 训练模型基于满血、无药、8 秒求解器。真实机器人使用 Smart 药水策略，但预测不包含药水收益；低血量风险与金币收益为启发式。
- 事件使用可见文字、展示卡牌和公开机制。变牌不窥探结果，目前以移除收益作启发式。未知界面明确失败，未知事件文字评分会标出启发式来源。

## 隔离运行

Linux 环境已有本地游戏/Wine 模板和 Release DLL 后：

```bash
python tools/prepare_autobot_runtime.py --output .local/autobot/experiment --workers 8
python -m runctl.batch --runtime-dir .local/autobot/experiment \
  --episodes 8 --seed-prefix EXPERIMENT --output .local/autobot/experiment/report
```

单 worker：

```bash
python -m runctl --runtime .local/autobot/experiment/worker-00/runtime.json \
  --episodes 1 --seed-prefix EXAMPLE --policy-config configs/bot-policy.json \
  --output .local/autobot/example-report
```

输出含完整配置、逐次决策、原生动作/状态及终局结果。异常和超时写入 `failure.json`，不算死亡，不自动换种子凑次数。诊断局与正式评测分开。

协议 `decisionMode: all` 启用全流程局外控制，`map` 保留历史基线。CLI 默认 `--policy model`，旧模式须指定 `--policy random-map`。进程和存档必须独占，不能连接玩家正在游玩的游戏或共享采集 worker。

## Windows 准备入口（原生 Windows 待验收）

在包含训练模型、Python 依赖和本次机器人代码的服务目录执行，替换三个实际路径：

```powershell
.\.venv\Scripts\python.exe tools\prepare_windows_autobot.py `
  --game "D:\SteamLibrary\steamapps\common\Slay the Spire 2" `
  --mod "C:\Users\www\Downloads\CombatSolver" `
  --output "D:\Sts2-Autobot"
.\.venv\Scripts\python.exe -m runctl --runtime "D:\Sts2-Autobot\runtime.json" `
  --episodes 1 --seed-prefix WINDOWS --output "D:\Sts2-Autobot\report"
```

`--mod` 应包含本次 DLL、manifest 和 NOTICE。若 RitsuLib 不在原游戏的 `mods/STS2-RitsuLib`，另传 `--ritsu-lib "实际安装目录"`。运行目录必须新建，放在游戏同一磁盘可硬链接资产节省复制。准备脚本建立独立游戏目录、独立 `override.cfg` 和 `%APPDATA%/CombatSolver-Autobot-...` 存档，并仅在该存档启用 Mod；原游戏和玩家存档不修改。

该独立目录机制已经通过 Wine 下 Windows 游戏实测到首个涅奥决策，初始 56/70 HP。这只验证存档隔离与 Mod 启动，不等于完整原生 Windows 对局验收。
