# CombatSolver 选牌评分开发版

在奖励、商店及事件选牌界面显示各候选的综合分数、相对原牌组的分差、短期和长期预期掉血。界面位于左侧，支持“重算”和“收起”；原生选择仍由玩家操作。

## 安装与启动

适配游戏 **0.111.0**、**RitsuLib 0.5.13**；模型只支持无额外修饰的单人静默猎手 A10。

1. 将补丁包中的 `CombatSolver` 文件夹合并进游戏 `mods` 目录，覆盖同名 DLL/manifest；保留现有 RitsuLib 和原 CombatSolver 的 Windows 内存清理辅助程序。此包是已有安装的开发补丁，不是完整依赖安装器。
2. 在本仓库启动评分服务：

   ```bash
   .venv-train/bin/python -m train.advisor_service
   ```

3. 启动游戏，打开奖励、商店或适配的事件选牌页面。

其他机器可用配套 `advisor-service` 包：安装 Python 3.11+，在包内执行 `pip install -r requirements.txt`，再执行 `python -m train.advisor_service`。模型位于包内 `checkpoints/train/selected`。服务必须与游戏运行在同一台机器，Linux Python 可与 Wine 游戏连接。

默认仅监听 `127.0.0.1:18765`。改端口时给服务传 `--port`，同时在游戏启动环境设置 `STS2_CARD_ADVISOR_URL=http://127.0.0.1:端口/score`；只接受回环 HTTP 地址。`STS2_CARD_ADVISOR_DISABLED=1` 可关闭评分模块。服务没有启动时，面板显示连接错误，启动服务后点击“重算”。

## 场景与口径

| 场景 | 分数含义 |
|---|---|
| 战斗／事件奖励 | 单张加入牌组，支持超过三张候选 |
| 商店 | 单张购入后的构筑分数，另显示价格和金币不足；无色牌可评分 |
| 事件移除／商店删牌界面 | 按具体牌组实例移除，保留重复牌的升级、附魔差别 |
| 升级页面 | 对深拷贝升级，原牌组不变 |
| 多选页面 | 单张边际分数，不是组合评分 |
| 强制选牌 | 原牌组显示为基准，不提示可跳过 |
| 随机变牌、附魔或未知操作 | 显示未支持，不套用加牌评分 |

Mod 0.30.2 起，按用户要求在商店候选中跳过“炼制药水”（`ALCHEMIZE`），保留其他牌和价格的对应关系，并在面板注明。商店只剩该牌时显示没有其他可评分卡牌。此规则不删除玩家已持有的牌，也不放宽其他不支持卡牌的校验。

综合分数越大越好；分差为相对原牌组的变化。当前只比较牌组变化，不计金币未来用途、事件额外代价、加牌/删牌/跳过的遗物触发或其他奖励按钮。一般事件“选择一张”中的新牌以“选入牌组”评估，不包含后续事件效果。

主线程读取当前牌组及卡牌状态、遗物顺序和完整标量计数、古代事件历史、地图，生成序列化副本。后台评分不读取 live 对象；页面和输入变化后清除旧分数并取消旧请求。升级只修改深拷贝。

近期分布按地图下两层可达边均匀传播；同类敌人等概率，普通房间当前包含该幕普通和弱敌池，未复刻弱敌切换和已遇敌人排除规则。未知房战斗概率默认 0.25，可通过服务参数 `--unknown-combat-probability` 调整；休息、商店、宝箱、古代事件按非战斗处理。当前以本幕首个 Boss 为长期目标，双 Boss 未独立规划第二场。这些均是明确的估计假设，不是读取未来 RNG。

开发版修正：短期 `mean` 按有效战斗次数归一化，不按楼层数归一化；非战斗房间不作为零伤害战斗加入平均。默认 `short_floor_weights` 改为 `[1, 1]`。新 Mod 额外导出后续公开房间类型分布，两层无可能战斗时服务向后寻找第一层可能战斗；旧 Mod 只给两层数据时无法作此地图扩展，需同时更新 DLL。仅有问号时，0.25 的战斗概率不会把条件平均伤害乘成四分之一。

模型仍按满血、禁药水、8 秒战斗求解条件评分，不代表残血死亡风险；训练生命上限为 70，其他值标记外推。遗物按训练预处理的 `normalized_relic_ids` 移出输入并在 UI 列明；其他不支持的卡牌、遗物、状态或目标显式报错。

服务端兼容原生遗物继承的 `IsWax=false`、`IsMelted=false` 标记，将其转换为训练使用的普通遗物状态；标记为 true 或类型错误时明确拒绝。真实计数器不补默认值，缺失、重复或额外字段的错误会列出遗物 ID 和字段名。

rollout 参数统一在 `configs/reward-policy.json`。金/蓝/白为 1:5:9，先抽类别再类内均匀抽牌，有放回；每个父节点 32 次采样加跳过、保留 4 个、展开 0–4 次，每个初始候选有 4^n 条末尾路径。未来卡池仍为静默猎手池。服务单次加载模型复用，串行处理请求；界面仅接收紧凑分数。

## 验证

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv-train/bin/python -m pytest tests/test_reward_policy.py tests/test_advisor_service.py -q
dotnet build vendor/CombatSolver/CombatSolver.csproj -c Release -p:CopyModOnBuild=false
bash vendor/CombatSolver/tools/verify-refactor-boundaries.sh
```

HTTP 测试需允许本地套接字。`tools/run_card_advisor_smoke.py --fixture <fixture.json>` 使用专用 `.runtime/prefix-card-advisor-smoke`，不使用玩家存档。`STS2_CARD_ADVISOR_SMOKE` 仅供显式结构测试，正常游戏不要设置。

2026-11-01：Python 27 项规则/输入测试与 1 项 HTTP 测试通过；Release 编译通过。真实 Wine/Godot 结构 fixture 的奖励、商店、事件加牌、移除、升级五项全部通过，分别显示 4/8/3/3/3 行，关闭后均隐藏旧分数。证据：`.local/card-advisor-smoke/fixtures.json.result.json`。

结构 fixture 使用合成快照，验证 C# HTTP 客户端、实际模型和真实 Godot 渲染，不等同于真实对局中逐个触发原生界面的捕获验收。可见游戏的布局、鼠标遮挡和字体仍需实机检查。

2026-11-01 服务热修复：复现原生继承标记导致的 `Incomplete relic state`，修复后 35 项离线服务/策略测试通过（其中新增 8 项）。实际选定模型接受蛇之戒指和精准剪刀携带的两个 false 标记，返回三张候选加跳过的 4 组有效分数；另验证笔尖计数器不被丢弃。不涉及 Mod DLL 更新，本次未重跑 Windows 可见游戏或 HTTP 套接字测试。

已有 Windows 服务安装可下载 `advisor-service-relic-fix.zip`，停止服务后将其中的 `train/advisor_service.py` 覆盖到原服务目录同名位置，重新运行原启动脚本，然后在游戏中点击“重算”。无需重新安装依赖或下载模型。

2026-11-01 古老牙齿服务热修复：仅放行 `ARCHAIC_TOOTH` 的 `StarterCard`、`AncientCard` 展示字段，与训练中的展示状态适配一致；变牌结果直接采用当前牌组，不重放获取遗物的效果。未知字段和蜡制/融化状态仍显式拒绝。14 项离线服务测试通过；实际模型在第二幕、带古老牙齿及变牌后的 `SUPPRESS` 的构筑上返回 4 组有效分数。本次未运行 Windows 可见游戏或 HTTP 套接字测试。

`advisor-service-tooth-fix.zip` 包含此前普通遗物状态修复，只覆盖 `train/advisor_service.py`，不修改 `configs/reward-policy.json` 中的长短期权重，也不包含模型或 Mod DLL。

2026-11-01 五轮书服务热修复：原生 `CardsAdded` 是累计计数，显示与回血触发使用模 5；服务先验证该值为非负 Int32，再转换为训练使用的 0–4 余数。不会修改实机计数或重放回血，满血构筑评分仍不包含局外回血收益。其他越界计数仍拒绝，并显示遗物 ID、字段、实际值与允许范围。

后续开发修复扩大到双截棍、铁棒、钓鱼竿、佩尔之翼、吃不完的糖及已核实的非循环阈值状态，详见 [实机计数转换](counter-state.md)。不是把所有越界计数取模；原版已归零的计数、有限次数和未知状态仍严格区分。

27 项离线服务测试通过；实际模型验证累计数 0、1、5、6、10 均返回 4 个候选分数，且 0/5/10 结果相同、1/6 结果相同，原始输入未被修改。本次未重跑 Windows 可见游戏或 HTTP 套接字测试。`advisor-service-book-fix.zip` 只更新服务脚本，包含此前普通遗物及古老牙齿修复，保留 Mod 0.30.2 的商店过滤与自定义权重配置。
