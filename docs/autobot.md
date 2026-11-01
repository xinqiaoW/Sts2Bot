# 模型驱动整局机器人（开发中）

原版单人静默猎手 A10、完整内容解锁/发现的统一起点，CombatSolver 执行战斗，Python 处理地图、事件、奖励、卡牌、遗物、商店、篝火、宝箱及嵌套选择。当前正在正式评测，尚未完成 100 局评测或原生 Windows 验收；见 [开发进度](autobot-progress.md)。

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
| `gold_hp_value` / `shop_reserve_gold` | 0.01 / 0 | 每金币扣分与保留金币；默认不为留钱额外扣分 |
| `potion_value` | 1 | 已有空药水槽时的资源估值 |
| `shop_remove_value` | 1 | 商店购买删牌服务的固定估值；减去价格代价后参与比较 |
| `event_max_hp_value` / `event_curse_cost` | 1 / 8 | 最大生命与诅咒代价；其他 `event_*` 参数同文件 |
| `rest_hp_fraction` | 0.55 | 篝火回血 HP 风险阈值 |
| `route_beam_width` / `route_risk_weight` | 64 / 2 | 地图路径保留宽度与低血量代价 |

分数越大越好。例如跳过 -20：卡牌 -19 时跳过，-18.99 才允许拿牌。可放弃的奖励、事件加牌、商店均执行门槛；商店另扣价格代价。强制选牌不伪造跳过，免费回血、升级、删牌不套用加牌的 +1 门槛。

商店每次购买后重新评分。只要还有买得起、满足加牌门槛且扣除金币代价后优于离开的卡牌，药水暂不参与竞争；之后才用剩余金币考虑药水。遗物和删牌仍按原有分数参与比较。100 金币现在扣 1 分，原来扣 4 分；药水有空槽时的净分为 `1 - 价格 × 0.01`，无空槽仍不买，不为花光金币强行买负收益商品。

后续 Python 补丁把商店删牌服务估值从写死的 5 改为可配置的 `shop_remove_value`，默认 1，与药水基础估值相同。是否付费删牌仍用该启发式；进入删牌界面后才用模型和 rollout 比较删哪张。`event_remove_value` 仅用于事件，不控制商店。买牌比较的是加牌综合分减去跳过综合分的增益，再扣金币代价；完成每次操作后根据新牌组、剩余金币及库存重新评分，可在一次进店中连续买牌、删牌和买药水。

在原有卡牌优先于药水的规则之后，若删牌和药水都买得起且净收益大于 0，正常局面暂缓药水、艰难局面暂缓删牌。优先级只在两个选项都有正收益时生效，不强买无收益商品。药水满槽仍不购买。商店没有可评分卡牌时，以当前构筑的跳过分支 rollout 判断风险，沿用 `crisis_boss_loss_fraction` 标准；不会因为卡牌售罄而默认判为正常。遗物仍参加净收益比较，卡牌与删牌之间仍按净收益决定。

短期分数现在是可能战斗的平均战损：非战斗房间不计入分母；问号的战斗概率同时进入战损与有效战斗次数。默认两层等权 `[1, 1]`。若下两层没有可能战斗，沿公开地图向后扩展到首个可能战斗层；不会读取该房实际生成的怪。若已无可达战斗，窗口为空，不虚构敌人。

战后奖励和宝箱的普通免费遗物直接领取，单件可领取遗物不因模型评分低而跳过。多个互斥遗物或古代事件选项才比较即时战斗力；商店另考虑价格。支持的累计计数转换为模型等价状态，见 [计数规则](counter-state.md)。

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

完整批次结束后可核对每次决策是否实际执行、拿牌门槛及 rollout 分支：

```bash
python -m runctl.audit --experiment .local/autobot/experiment/report \
  --output .local/autobot/experiment/audit.json
```

核对要求原生事件、动作和终局原始文件仍在，不只读取汇总胜负。

协议 `decisionMode: all` 启用全流程局外控制，`map` 保留历史基线。CLI 默认 `--policy model`，旧模式须指定 `--policy random-map`。进程和存档必须独占，不能连接玩家正在游玩的游戏或共享采集 worker。

## Windows 本地试用（原生 Windows 待验收）

0.30.4 测试包先将 `advisor-service` 合并到已有服务目录，保留 `.venv` 和 `checkpoints/train/selected`；`CombatSolver` 是本次 Mod 文件夹。无需重新下载模型、安装依赖或启动 HTTP 评分服务。可先试用，100 局评测尚未完成。

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

准备成功后，双击输出目录的 `启动自动爬塔.bat` 即可。每次启动新的一局并建立独立报告目录；它会使用准备时的 Python 和服务路径。移动服务目录后需重新准备启动器。一次只运行一个机器人；停止时在终端按 Ctrl+C。报错时保留终端文字、报告目录内的 `failure.json` 以及输出目录中的 `native.log`。

若出现 `No space left on device`，将 `--output` 放到游戏所在磁盘的新目录，避免跨盘复制整套游戏；删除确认属于本次失败准备的残留目录可释放空间。模型和 Python 服务目录可以仍在另一磁盘。

0.30.3 首次 Windows 试用发现读取 `decision.json` 的瞬时 `PermissionError`。Python 通信补丁使用允许删除/替换共享的 Windows 文件句柄，并对 Windows 文件占用/替换窗口最多重试约 1 秒；持续权限错误、JSON 损坏和协议身份错误仍失败，不重新发送动作。覆盖服务目录的 `runctl/env.py` 后重新启动机器人即可，无需重装 Mod、模型或独立游戏目录。31 项通信协议回归通过，其中包括瞬时占用、持续拒绝访问和损坏 JSON；Windows 原生使用效果仍待实际验证。

### 已有 Windows Bot 升级到 0.30.4

先退出 Bot 和对应游戏，将包内 `advisor-service` 合并覆盖原服务目录；备份个人配置，本次默认配置包含新的商店估值。将包内 `CombatSolver` 的 DLL、JSON、NOTICE 和 MemoryCleaner 覆盖到 **独立 Bot 游戏** 的 `game/mods/CombatSolver`。只更新 Downloads 中用来准备的 Mod 文件夹，不会更新已经创建的独立游戏。

例如包解压到 Downloads 后，在 PowerShell 执行（服务文件夹也应已合并覆盖）：

```powershell
$ErrorActionPreference = 'Stop'
$mod = 'C:\Users\www\Downloads\CombatSolver'
$bot = 'D:\Sts2-Autobot-0303'
Copy-Item -LiteralPath "$mod\CombatSolver.dll", "$mod\CombatSolver.json", "$mod\THIRD_PARTY_NOTICES.md", "$mod\CombatSolver.MemoryCleaner.exe" -Destination "$bot\game\mods\CombatSolver" -Force
$runtimePath = Join-Path $bot 'runtime.json'
$runtime = Get-Content -LiteralPath $runtimePath -Raw -Encoding UTF8 | ConvertFrom-Json
$runtime | Add-Member -NotePropertyName combat_search_mode -NotePropertyValue 'settings' -Force
[IO.File]::WriteAllText($runtimePath, ($runtime | ConvertTo-Json -Depth 20), [Text.UTF8Encoding]::new($false))
```

之后仍双击原来的 `启动自动爬塔.bat`。

### 搜索深度与时间

`runtime.json` 的 `combat_search_mode` 有两种模式：

- `settings`：读取 **Bot 独立游戏存档** 中的 CombatSolver 性能档位、自定义短搜/深搜时间与并行度，允许深搜。新建 Windows Bot 默认使用此模式；已有目录需按上面命令修改一次。
- `evaluation8s`：旧评测模式，固定 8 秒短搜、单线程，不启动深搜；未写字段的旧运行目录保持此行为。

在 Bot 游戏中的 CombatSolver 设置调整性能档位/自定义预算，下一局读取该档案。独立档案路径在 `runtime.json` 的 `data_dir`，设置文件是其中的 `combat_solver_settings.json`；原游戏的设置不会自动同步到 Bot。`settings` 默认单场战斗等待上限 1800 秒、整局 14400 秒；这是故障等待上限，不是每次搜索预算。可分别用 runtime 的 `combat_timeout_seconds`（最多 3600）及 CLI `--timeout`（最多 14400）调整。

选牌 rollout 另由服务目录 `configs/reward-policy.json` 的 `depth_schedule`、`samples_per_parent`、`keep_per_parent` 及 `configs/bot-policy.json` 的危机扩展参数控制，与战斗搜索档位独立。修改后重启 Bot。原生日志 `run_started` 记录实际搜索模式、预算与并行度，方便确认设置生效。
