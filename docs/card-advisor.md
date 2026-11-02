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

长期分数默认混合保留末尾路径的前 25% 与后 25%，两组权重各为 50%。独立服务在 `configs/reward-policy.json` 调整 `leaf_top_fraction`、`leaf_bottom_fraction`、`leaf_top_weight`、`leaf_bottom_weight`。组内沿用 `leaf_rank_power=1` 的排名加权（较差组从最差路径开始排名）；设为 0 可取普通平均。前后两组仍来自择优剪枝后的路径，不是所有未来奖励的真实概率分布。Bot 的对应参数集中在 `configs/bot-policy.json`。

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
