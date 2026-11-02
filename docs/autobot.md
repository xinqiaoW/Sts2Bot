# 模型驱动整局机器人（开发中）

原版单人静默猎手 A10、完整内容解锁/发现的统一起点，CombatSolver 执行战斗，Python 处理地图、事件、奖励、卡牌、遗物、商店、篝火、宝箱及嵌套选择。当前正在正式评测，尚未完成 100 局评测或原生 Windows 验收；见 [开发进度](autobot-progress.md)。

## 参数和选牌门槛

统一参数在 [bot-policy.json](../configs/bot-policy.json)，底层 rollout 参数沿用 [reward-policy.json](../configs/reward-policy.json)。修改后重启机器人进程。

| 参数 | 默认值 | 含义 |
| --- | --- | --- |
| `short_weight` / `long_weight` | 0.28 / 0.72 | 近期战斗力充足时的短期与长期权重 |
| `short_strength_loss_threshold` | 10 | 当前牌组近期每场平均预计掉血超过此值，视为战斗力不足 |
| `elite_target_loss_threshold` | 20 | 本幕前6层，当前牌组预计精英平均掉血严格超过此值则以精英为长期目标 |
| `boss_target_after_act_floor` | 6 | 本幕超过此层（默认第7层起）强制以Boss为长期目标 |
| `weak_short_weight` / `weak_long_weight` | 0.72 / 0.28 | 近期战斗力不足时的短期与长期权重 |
| `normal_card_min_gain` | 1 | 正常加牌必须严格超过跳过分加此值 |
| `crisis_card_min_gain` | 0 | 艰难局面仍要求加牌优于跳过 |
| `crisis_boss_loss_threshold` | 40 | 正常 rollout 最佳长期 Boss 预期掉血严格超过此值则判为艰难并扩大搜索；不按最大 HP 比例计算 |
| `samples_per_parent` | 64 | 普通局面每个父节点抽样数，另加跳过 |
| `keep_per_parent` | 6 | 普通局面每个父节点保留数 |
| `lookahead_pairs` | 1 | 最前面几组使用两步展开后剪枝，范围 0–3；0 恢复逐层剪枝 |
| `leaf_top_fraction` / `leaf_bottom_fraction` | 0.25 / 0.25 | 分别取末尾路径中评分最好和最差的比例 |
| `leaf_top_weight` / `leaf_bottom_weight` | 0.5 / 0.5 | 两组长期分数的权重，按总和归一化；后者为 0 可恢复只看较好组 |
| `leaf_rank_power` | 1 | 每组内部按 1/排名^此值加权；较差组从最差开始排名，0 为组内普通平均 |
| `crisis_samples_per_parent` | 128 | 艰难局面每个父节点抽样数 |
| `crisis_keep_per_parent` | 8 | 艰难局面每个父节点保留数 |
| `reward_rollout_depth` | 3 | 仅战后奖励选牌使用固定深度，可选 3、4、5，不受剩余层数限制 |
| `crisis_extra_depth` | 1 | 艰难局面额外深度；战后奖励因此默认搜 4 层，最高 6 层 |
| `max_rollout_depth` | 4 | 商店、事件、删牌等其他卡牌搜索的上限，仍受剩余层数约束 |
| `gold_hp_value` / `shop_reserve_gold` | 0.01 / 0 | 每金币扣分与保留金币；默认不为留钱额外扣分 |
| `potion_value` | 1 | 已有空药水槽时的资源估值 |
| `shop_remove_value` | 1 | 商店购买删牌服务的固定估值；减去价格代价后参与比较 |
| `event_max_hp_value` / `event_curse_cost` | 1 / 8 | 最大生命与诅咒代价；其他 `event_*` 参数同文件 |
| `rest_hp_fraction` | 0.55 | 篝火回血 HP 风险阈值 |
| `route_beam_width` / `route_risk_weight` | 64 / 2 | 地图路径保留宽度与低血量代价 |

分数越大越好。例如跳过 -20：卡牌 -19 时跳过，-18.99 才允许拿牌。可放弃的奖励、事件加牌、商店均执行门槛；商店另扣价格代价。强制选牌不伪造跳过，免费回血、升级、删牌不套用加牌的 +1 门槛。

两步剪枝先展开一张未来牌（或跳过），再对每个候选展开下一张，按第二步最佳战损给第一步候选排序；保留前 K 个第一步候选，以及每个候选最好的 K 个第二步后继。弱单卡组成的强配合因此有机会留下。第二步实际计入深度和最终路径，不凭空给组合加分；末尾只剩一步时正常单步剪枝。默认仅前两次未来加牌使用两步展开，后续逐层剪枝。初始奖励选项和跳过均使用相同位置的随机采样，不指定任何必拿搭配。金/蓝/白概率仍为 1:5:9。

每个初始选项的末尾路径数仍为 K^深度：默认普通局面 6³=216、艰难局面 8⁴=4096。两步展开会额外评估随后被丢弃的分支；提高深度、保留宽度或 `lookahead_pairs` 会显著增加时间与内存。日志 `stats.per_depth` 的 `pruning` 标明 `two_step` 或 `one_step`，`evaluated_paths` 包含未保留的实际评估路径。

长期评分现在同时使用较好与较差的末尾路径：默认前 25% 和后 25% 各占 50%。这里“前”按分数从高到低（掉血从低到高）排序。4096 条路径时每组各取 1024 条；组内仍使用排名权重，较差组中最差路径权重最大。深度 0 等小集合可能出现两组重叠，每个节点的贡献相加，总权重仍为 1；不制造额外末尾节点。高级参数 `leaf_top_k` 仍仅限制较好组的条数，默认 null。

Bot 选牌日志的 `long_tail_summaries` 分别列出两组和混合后的预计掉血，以及参与计分的路径数；其中 `option_index` 是模型候选序号，若有不支持的候选被投影排除，不保证等于原 UI 选项序号。评分服务结果直接包含 `top_expected_hp_loss` / `bottom_expected_hp_loss`。艰难局面的 40 血阈值也使用混合后的正常 rollout 长期值，所以此修改可能使更多局面触发额外搜索。两组都是已经过择优剪枝的末尾路径，后 25% 不代表所有未来坏情况，也不是实际获得卡牌的概率分布。

安装独立选牌搜索补丁时，先停止 Bot 和评分服务，把补丁解压到新文件夹，使用已安装服务的 Python 执行补丁内的 `tools/install_card_search_update.py --target <advisor-service 路径>`。最新安装器备份原文件至目标目录的 `update-backups/card-search-*`，把前后组比例设置为 25%/25%、权重设置为 50%/50%，保留已有搜索宽度、两步剪枝设置、长短期权重、深度及门槛；旧版本缺失的搜索字段补默认值。若启动命令通过 `--policy-config` 指向另一个文件，需要同步修改那个文件的参数。此补丁不包含 DLL 或模型。

商店每次购买后重新评分。只要还有买得起、满足加牌门槛且扣除金币代价后优于离开的卡牌，药水暂不参与竞争；之后才用剩余金币考虑药水。遗物和删牌仍按原有分数参与比较。100 金币现在扣 1 分，原来扣 4 分；药水有空槽时的净分为 `1 - 价格 × 0.01`，无空槽仍不买，不为花光金币强行买负收益商品。

后续 Python 补丁把商店删牌服务估值从写死的 5 改为可配置的 `shop_remove_value`，默认 1，与药水基础估值相同。是否付费删牌仍用该启发式；进入删牌界面后才用模型和 rollout 比较删哪张。`event_remove_value` 仅用于事件，不控制商店。买牌比较的是加牌综合分减去跳过综合分的增益，再扣金币代价；完成每次操作后根据新牌组、剩余金币及库存重新评分，可在一次进店中连续买牌、删牌和买药水。

在原有卡牌优先于药水的规则之后，若删牌和药水都买得起且净收益大于 0，正常局面暂缓药水、艰难局面暂缓删牌。优先级只在两个选项都有正收益时生效，不强买无收益商品。药水满槽仍不购买。商店没有可评分卡牌时，以当前构筑的跳过分支 rollout 判断风险，沿用 `crisis_boss_loss_threshold` 的绝对掉血标准；不会因为卡牌售罄而默认判为正常。遗物仍参加净收益比较，卡牌与删牌之间仍按净收益决定。

短期分数现在是可能战斗的平均战损：非战斗房间不计入分母；问号的战斗概率同时进入战损与有效战斗次数。默认两层等权 `[1, 1]`。若下两层没有可能战斗，沿公开地图向后扩展到首个可能战斗层；不会读取该房实际生成的怪。若已无可达战斗，窗口为空，不虚构敌人。

战后奖励和宝箱的普通免费遗物直接领取，单件可领取遗物不因模型评分低而跳过。多个互斥遗物或古代事件选项才比较即时战斗力；商店另考虑价格。支持的累计计数转换为模型等价状态，见 [计数规则](counter-state.md)。

普通 rollout 每个父节点保留 4 个分支，深度 n 对应每个初始候选 4^n 个末端节点；艰难局面默认 6^n。白/蓝/金抽样比 9:5:1。日志保存分数、跳过分、风险状态、深度、实际分支统计及门槛排除项。

战后奖励固定深度以 0.30.5 Mod 导出的 `context.postCombat=true` 为准；事件即使使用相同卡牌奖励页面也不采用固定深度。先按配置的普通深度评估风险，超过 40 则按既有危机采样/分支参数并增加 1 层重新搜索；不因距 Boss 只剩一层而缩短。正常深度 3/4/5 每个候选分别有 64/256/1024 个末端节点，危机深度 4/5/6 在默认分支数 6 下分别有 1296/7776/46656 个末端节点。

当前配置示例（合并到已有 JSON，不重复字段）：

```json
"short_weight": 0.28,
"long_weight": 0.72,
"crisis_boss_loss_threshold": 40.0,
"reward_rollout_depth": 3,
"crisis_extra_depth": 1
```

恰好预计掉血 40 不算艰难；此标准仍基于最佳长期 Boss 预期掉血，未使用当前剩余 HP。旧 `crisis_boss_loss_fraction` 已弃用，加载旧覆盖配置会明确提示该字段被忽略；请使用绝对 HP 阈值。

## 卡牌rollout敲牌（0.30.15）

`configs/bot-policy.json` 新增 `rollout_max_upgrades`，默认1，允许0–6。每个父节点在还有升级次数时，比较当前可升级牌，额外提供一条当前长期目标掉血最低的升级候选，与随机抓牌、跳过共同竞争原保留名额。设0恢复只抓牌/跳过；每层仍保留K条，所以每个初始节点仍有K^n个末端。

一次升级占一层深度、不增加牌数；例如深度3可走“拿一张牌 → 升级这张牌 → 跳过”。新奖励牌和未来模拟拿到的牌都能升级，未升级的实际短期评分不提前获得升级收益。每条路径最多敲配置次数；候选没有保证保留，仍须按掉血预测竞争。未把真实篝火数量或休息机会成本纳入此假设。

`upgrade_probability`是随机抓到升级版卡牌的概率，和敲已有牌独立。日志路径原有卡牌字典表示抓牌，null表示跳过，`{"action":"upgrade","deck_index":3,"card":{"id":"...","upgrade":1}}`表示修改该实例；不要把升级操作追加为新卡。leaf的upgrade_count与stats的upgrade_candidates/upgrade_branches可查看升级次数和额外计算量。

## 事件加牌与关键牌保护（0.30.14）

事件使用当前牌组的直接预测，不以未来rollout中假设拿到的卡牌补救当前损害。目标与权重沿用血量预算规则：当前HP减短期总损失与目标损失仍高于安全余量才算充足；已知双Boss长期评分取较难者，预算累计两场。此规则可能比仅看普通怪或当前HP更保守。

| 参数 | 默认 | 含义 |
| --- | --- | --- |
| `event_card_min_gain` | 1 | 安全局面下，强制加牌的构筑综合增益须严格超过此值，否则优先安全的非加牌选项 |
| `event_unknown_card_cost` | 3 | 尚未展示或模型不支持的强制加牌，每张的启发式代价；不是掉血预测 |
| `bridge_key_card_loss_threshold` | 3 | 删牌使短期或长期预计掉血增加至少此值，则视为关键牌 |

覆盖羽化、两张开悟、满屋芝士、脑蛭、害虫杀手、异鸟巢、传送带和打造时间的明确加牌选项。两张开悟按两张一起评估，未展示的随机候选不窥探；既没有可安全拒绝的选项时，仍须选合法动作。存在明确构筑收益的牌仍可选择。尚未覆盖的事件保留原启发式。

滑脚木桥每次用当前显示的牌及其牌组实例序号重新评估；关键牌和未能评估的牌优先安全重抽，普通牌可正常删除。重抽扣除当前显示的HP后必须仍高于生存预算余量，否则不再重抽，避免为了保牌耗尽血量。日志 `event_combat` 包含前后损失、共同权重、预算、关键牌增幅，`event_rejected_options` 给出本次被规则排除的选项。模型可能低估配合重要性，阈值并非关键牌的绝对保证。

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

0.30.5 测试包先将 `advisor-service` 合并到已有服务目录，保留 `.venv` 和 `checkpoints/train/selected`；`CombatSolver` 是本次 Mod 文件夹。无需重新下载模型、安装依赖或启动 HTTP 评分服务。可先试用，100 局评测尚未完成。

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

### 已有 Windows Bot 升级到 0.30.5

0.30.6 提供另一个仅含 Mod 的 Windows 通信修复包，解决发布决策时的文件替换冲突。已有 0.30.5 服务的用户只需退出 Bot 后覆盖独立游戏 `game/mods/CombatSolver` 中的本次文件；不覆盖配置、模型或 Python。短暂占用约 1 秒内有界重试，持续权限问题仍会报告完整目标路径和保留的临时文件；不通过反复发送动作恢复。

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

战后选牌深度使用 `configs/bot-policy.json` 的 `reward_rollout_depth`；商店/事件/删牌仍使用 `configs/reward-policy.json` 的 `depth_schedule` 和 Bot 的 `max_rollout_depth`。Bot 的普通采样、保留数、两步剪枝和艰难扩展参数现在统一在 `bot-policy.json`；单独启动评分服务使用 `reward-policy.json` 中的普通宽度和两步剪枝参数。两步剪枝和宽度适用于各类卡牌搜索，固定深度仍仅用于战后奖励。这些与战斗搜索档位独立。修改后重启 Bot。原生日志 `run_started` 记录实际搜索模式、预算与并行度，方便确认设置生效。

0.30.5 的 Boss 战把持续能力增益的中间路线保留加分乘以 1.5；使用已捕获的 Boss 房间类型，包含非幕末 Boss。搜索预算和完整路线最终战损排序不变，不意味着必定先出能力或已经证明整局胜率更高。


### 玩偶室固定策略（2026-11-02）

初始页按公开选项 ID 固定选择第二项 `TAKE_SOME_TIME`（花点时间慢慢来）；后续排除宾邦 `BING_BONG`，包括原生 `relic=null`、仅带本地化 TextKey/title 的页面。其余候选仍按原评分比较，继续按钮正常处理。指定选项不可用/会致死、只有宾邦或未知页面时明确失败，不自动改选随机项。策略在单选快捷路径之前执行。

小补丁 `Sts2Bot-doll-room-update.zip` 的安装器 `tools/install_doll_room_update.py --target <advisor-service>` 自动备份并只修补事件入口，不覆盖宽度、深度、长短期权重、尾部分数或等待期限。92 项相关策略测试及 2 项安装器测试通过；Windows 事件现场未验证。


## 根据近期战斗力切换权重（2026-11-02）

使用当前牌组（不拿牌/不改变构筑的基准分支）的近期每场平均预期掉血判断，一次决策内所有候选使用同一组权重。默认不超过 10 点时，短期/长期为 0.28/0.72；严格超过 10 点时为 0.72/0.28。即使某张牌能让近期战损降到阈值以内，也不为它单独切换权重，避免候选比较口径不同。

配置键：`short_strength_loss_threshold` 是掉血阈值；`short_weight` / `long_weight` 是充足时的权重；`weak_short_weight` / `weak_long_weight` 是不足时的权重。两组分别归一化，设为相同即可保持固定权重。Bot 使用 configs/bot-policy.json（或 --policy-config 指定文件），独立评分服务使用 configs/reward-policy.json。

平均值按实际可能发生的战斗权重计算，商店/篝火不作零损战斗计入分母；沿用现有无近期战斗时的路线延伸策略。判定始终使用每场平均损失，即使短期评分配置为 sum。若输入完全没有可评分的近期战斗，记录 no_short_combat，不把未知情况宣称为战斗力充足，并使用原 short_weight/long_weight。

输出的 score_weighting 记录 mode（sufficient/insufficient/no_short_combat）、baseline_short_expected_hp_loss、阈值及实际归一化后的权重。Bot 的 decisions.jsonl 也记录该字段。判定复用已有模型结果，不增加推理/rollout。Boss 预计战损超过 40 的艰难局面判定、搜索深度、留牌门槛与尾部分数聚合均保持独立。

模型仍以满血构筑预测；本阈值是战斗能力启发式，不是当前血量下的死亡概率。离线验证覆盖阈值等号、候选排序真实切换、共同权重、mean/sum 判定一致、无战斗输入、配置合法性及 Bot 记录；未验证 Windows 实机效果。

更新包 Sts2Bot-adaptive-weights-update.zip：停止 Bot 和评分服务后，用已安装 Python 执行 tools/install_adaptive_weights_update.py --target <advisor-service>，自动备份并补齐缺失配置，保留已有宽度/深度/权重/阈值。包含玩偶室规则，保留 0.30.8 超时相关文件，无需更新 DLL 或模型。


## 旧规则：弱怪池与 Boss 战后选牌（0.30.9，已由0.30.10替代）

所有幕统一：已完成普通战斗数第一幕 <3、后续幕 <2 时，短期评估本幕弱普通怪池，长期 rollout 用本幕精英池。完成最后一场弱怪后的奖励页开始以本幕可见 Boss 为长期目标，短期恢复原来的可见路线近战窗口；无战斗房间不计入平均分母。

本幕最后一个 Boss 战后，短期改用下一幕弱普通怪池，长期改用下一幕精英池。双 Boss 第一场结束不跨幕，目标为第二 Boss。最终通关后没有未来战斗，评分归零并倾向跳过。池内等概率；缺训练覆盖的目标显式报告，整个精英池无覆盖时失败，不偷偷回退 Boss。

跨幕保留当前真实牌组、遗物和古代事件历史，只修改模型的敌人幕上下文；不假设获得下一幕古代遗物，不读取下一幕实际怪物序列或 Boss。日志报告 cross_act_projection_without_future_rewards，这属于当前构筑面对下一幕敌人的外推。

Bot 的战后选牌仍使用 reward_rollout_depth（默认 3）与危机额外深度。独立面板跨幕用 configs/reward-policy.json 的 post_boss_rollout_depth（默认 3，可设 0–6），避免已通关幕的距离为零导致完全不 rollout；Bot 非战后选牌的跨幕备选深度对应 configs/bot-policy.json 同名键。宽度、前后尾部分数组合、动态长短期权重均沿用原配置。

日志新增 scoring_horizon（mode、encounter_act_id、long_target_room、long_targets、short_targets）。模型叶子损失看 target_hp_loss；兼容字段 boss_hp_loss 只在 Boss 目标时非空。crisis_boss_loss_threshold 保留旧名称，实际比较当前长期目标的预测损失；projected_long_loss 总是报告该损失，projected_boss_loss 仅在目标为 Boss 时非空。

Windows 使用 Sts2Bot-0.30.9-scoring-horizon.zip，退出游戏、Bot、评分服务后，执行包内 tools/install_scoring_horizon_update.py --target <advisor-service目录> --bot <含runtime.json的Bot目录>。安装器读取 runtime.game_dir 定位真实 Mod，备份旧文件并更新两端；只补缺失配置，不覆盖已有值，不改 runtime.json。包括既有玩偶室、动态权重和 0.30.8 超时修复。不需要重新下载模型或重建游戏副本。


## 当前规则：精英风险决定长期目标（0.30.10，替代0.30.9的固定弱怪规则）

每幕前6层：对未拿候选牌、未rollout的当前构筑估计精英池平均掉血。严格大于 elite_target_loss_threshold（默认20）时，长期目标为本幕精英；小于或等于20时为本幕Boss。actFloor > boss_target_after_act_floor（默认6）后强制Boss，即第7层起生效。全局楼层不参与这个判断。

所有候选共用一次判断，精英探测为单次构筑分布预测。普通战斗计数只用于短期弱怪/普通怪池，不再决定长期目标；短期充分/不足的0.28/0.72与0.72/0.28权重规则独立保留。

本幕Boss战后按下一幕第0层重新判断：短期仍看下一幕弱普通怪；如果下一幕精英预计掉血超过阈值，长期看下一幕精英，否则看下一幕公开Boss池的平均，不读取实际隐藏Boss。双Boss第一场后仍处于当前幕；最终通关无未来战斗。

Bot配置 configs/bot-policy.json；独立评分服务 configs/reward-policy.json：
```json
"elite_target_loss_threshold": 20.0,
"boss_target_after_act_floor": 6
```
若用了自定义 --policy-config，请修改对应文件。日志 scoring_horizon 包含 estimated_elite_loss、target_reason、evaluated_act_floor、阈值、所用目标池；因楼层强制Boss时 estimated_elite_loss=null，表示未额外探测。旧面板缺actFloor会记录明确的兼容警告并使用Boss；配套更新两端可启用新规则。

安装包 Sts2Bot-0.30.10-elite-risk-target.zip 可以直接更新，不必先安装0.30.9。退出Bot、游戏和评分服务后，执行包内 tools/install_scoring_horizon_update.py --target <advisor-service> --bot <含runtime.json的Bot目录>；备份原文件、读取真实game_dir更新DLL和Python、保留已有配置值并补齐新字段。

## 故事书禁选（0.30.16）

按用户要求，先古事件中禁止STORYBOOK（故事书），避免获得会损失最大生命的至亮之焰。禁选优先于唯一选项和模型评分；无其他合法选项时明确停止。已持有的卡和遗物不修改，战斗出牌规则未变；该牌原本已不在普通rollout抽样池中。

## 分享与复现游戏种子

Bot 默认生成随机种子；控制台开局行与 summary.json 记录规范化后的实际种子。游戏输入会将 O 转成 0、I 转成 1 并转大写，新 Bot 同样处理。旧版 WINDOWS 前缀直接参与 RNG，与手工输入后的 W1ND0WS 不等价，旧局不能按新规则宣称复现。

指定一局精确种子（不会追加 0）：

```powershell
.\.venv\Scripts\python.exe -m runctl --runtime 'D:\Sts2-Autobot-0303\runtime.json' --episodes 1 --seed '你的种子' --policy-config configs\bot-policy.json --output 'D:\Sts2-Autobot-0303\reports\seed-check'
```

当前 Bot 固定静默猎手 A10，使用全解锁、全部遭遇已发现的完整内容条件；第一幕按原版 act_selection 随机流选择。人类复现需同游戏版本、同角色难度、完整内容条件、无额外自定义词条且第一幕选择随机。种子固定随机流，并不保证不同路线/操作之后的所有奖励仍一致。未解锁内容或初见安排在原版就可能改变生成，不能对任意新手存档保证相同。
