# 自动爬塔 Bot

Bot 使用独立游戏与存档，负责地图、事件、奖励、商店和篝火；战斗由 CombatSolver 求解。当前支持静默猎手 A10，适配游戏 0.111.0。模型与自动 Bot 在同一 Python 进程运行，无需另开 HTTP 评分服务。

## Windows 准备与启动

在已有模型和依赖的 advisor-service 目录中执行，替换实际路径：

```powershell
.\.venv\Scripts\python.exe tools\prepare_windows_autobot.py `
  --game 'D:\SteamLibrary\steamapps\common\Slay the Spire 2' `
  --mod 'C:\Users\www\Downloads\CombatSolver' `
  --output 'D:\Sts2-Autobot'
```

游戏目录应包含 `SlayTheSpire2.exe`，Mod 应包含配套 DLL、manifest、NOTICE 与 MemoryCleaner。RitsuLib 不在原游戏 `mods/STS2-RitsuLib` 时另传 `--ritsu-lib <目录>`。输出须是新目录；与游戏放在同一磁盘可以硬链接大资产，避免跨盘复制耗尽空间。

准备脚本建立独立游戏、设置与 `%APPDATA%\CombatSolver-Autobot-...` 存档。以后双击输出目录的 `启动自动爬塔.bat` 即可。启动器绑定准备时的服务目录和 Python 路径；一次只启动一个 Bot。Ctrl+C 停止，保留报告与日志。

不指定种子时每局随机；精确复现单局：

```powershell
.\.venv\Scripts\python.exe -m runctl `
  --runtime 'D:\Sts2-Autobot-0303\runtime.json' `
  --episodes 1 --seed '你的种子' `
  --policy-config configs\bot-policy.json `
  --output 'D:\Sts2-Autobot-0303\reports\seed-check'
```

Bot 使用全解锁、全部遭遇已发现的内容条件，第一幕按原版 `act_selection` 随机流选择。人类复现需同游戏版本、角色、难度、完整内容条件，无额外自定义词条，第一幕选随机。种子规范化与游戏一致：大写，O→0、I→1。后续操作不同会消耗不同随机流，不能保证不同路线仍收到同样奖励。`--seed-prefix` 是保留的批量兼容入口，会追加局序号，不能当作精确种子输入。

## 已有 Windows Bot 升级

当前统一安装器为 `tools/install_bot_update.py`。旧名称 `install_scoring_horizon_update.py` 仅转发到同一实现。历史独立补丁的安装器不再推荐用于当前版本。

退出 Bot、游戏和评分服务，将新包解压到独立目录，使用已有 Python 执行**新包中的**安装器。例如完整包结构为 `<新包>\advisor-service\tools\install_bot_update.py`：

```powershell
$patch = 'C:\Users\www\Downloads\新包目录'
$service = "$env:USERPROFILE\Downloads\advisor-service"
& "$service\.venv\Scripts\python.exe" "$patch\advisor-service\tools\install_bot_update.py" `
  --target $service --bot 'D:\Sts2-Autobot-0303'
```

若补丁根目录直接包含 `tools`，将脚本路径改为 `$patch\tools\install_bot_update.py`。安装器读取 `runtime.json` 中的真实 `game_dir`，备份到服务目录 `update-backups`，更新配套 Python/Mod，仅补齐缺失参数，保留既有值与 runtime。无需重建独立游戏或下载模型。不要覆盖整个 configs 文件夹，也不要仅替换 Downloads 中的源 Mod 而遗漏实际运行副本。

## 配置与排障

参数语义及优先级统一见 [当前配置规则](policy-configuration.md)。`runtime.json` 在 Bot 输出目录，例如 `D:\Sts2-Autobot-0303\runtime.json`；Bot 策略在服务目录 `configs\bot-policy.json`。若启动时指定其他 `--policy-config`，修改对应文件。

`combat_search_mode="settings"` 使用独立游戏内 CombatSolver 搜索设置。此模式下单次局外决策 `action_timeout_seconds` 允许 1–3600 秒，模型 Bot 默认 1800 秒；整局默认 14400 秒。固定评测模式的决策上限为 300 秒。时间预算必须符合原生协议，不能无限调大。

报告目录含 `summary.json` 或 `failure.json`、逐次决策 `decisions.jsonl`、最终配置快照。原生轨迹在 `runtime.data_dir\combat_solver_runs\<runId>`，游戏日志由 `runtime.log_path` 指定。用同一 runId 关联记录，日志可能包含多次启动；不要仅凭最后一次 INIT 版本判断旧失败属于哪个版本。

`An unaccepted native request already exists` 表示有请求尚未被消费。先停止这一独立 Bot，检查所属 run 与请求；不要删除仍在运行实例的通信文件。`Native process exited` 是外层提示，需查看此次启动后的原生日志；退出时的资源泄漏消息通常不足以定位最初原因。运行失败、超时、人工取消单独记录，不计为游戏死亡。

## 策略边界

普通免费遗物直接领取；互斥遗物与先古奖励才比较，商店另扣价格。卡牌支持加入、按实例删牌与升级；变牌等不确定效果使用明确启发式。事件加牌按当前构筑直接评估，强势局面避免无益强制加牌；吊桥重抽受血量预算约束。禁选故事书奖励及涅奥龙涎香组合奖励，不禁用普通龙涎香药水。

商店可连续操作，每买一次重评。满足门槛的正收益卡牌优先于药水；正常局面正收益删牌优先于药水，危机时反之。遗物仍参加净收益比较。药水奖励满槽时按配置优先级替换最低者；商店满槽仍不买药。金币、删牌服务与药水的估值是启发式，不是模型预测。

只使用当前公开状态、地图和公开遭遇池，不读取未知房实际内容、未来奖励或游戏 RNG。模型不支持的特征会记录，真实库存不被修改。计数转换见 [计数规则](counter-state.md)，效果边界见 [遗物规则](relic-rules.md)。

## 本地 Linux 评测

需要已有的本地游戏/Wine 模板与配套 Release DLL：

```bash
python tools/prepare_autobot_runtime.py --output .local/autobot/experiment --workers 4
python -m runctl.batch --runtime-dir .local/autobot/experiment \
  --episodes 4 --seed-prefix EXPERIMENT --output .local/autobot/experiment/report
```

该命令仅供主动发起新评测时使用；当前实验已暂停。保留原生轨迹后，可用 `python -m runctl.audit --experiment <报告目录> --output <审计文件>` 核对真实动作。当前结果及验收范围见 [进度](autobot-progress.md)。
