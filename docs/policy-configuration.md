# 当前评分与配置规则

此页描述当前代码；历史版本说明不用于推断当前默认值。配置入口为 `train/policy_defaults.py`，JSON 是可编辑的覆盖值。缺字段继承默认值，未知字段报错；更新安装器只补缺项，保留已有值。

## 哪份配置生效

| 文件/设置 | 使用者 | 作用 |
| --- | --- | --- |
| Bot 目录 `runtime.json` | `runctl` | 游戏路径、独立存档、日志路径、整局/决策超时、战斗搜索模式 |
| 服务目录 `configs/bot-policy.json` | 自动 Bot | 选牌、商店、事件、路线与搜索参数 |
| `--policy-config <文件>` | 自动 Bot | 在默认 Bot JSON 上覆盖指定字段 |
| 服务目录 `configs/reward-policy.json` | 评分模块 | 独立评分服务全部参数；Bot 的评分专用字段，如稀有度、短期层权重、推理批量 |
| CombatSolver 游戏内设置 | 战斗求解器 | `combat_search_mode="settings"` 时的战斗时间预算与搜索宽度，与卡牌 rollout 分开 |

Bot 与 reward 配置共有的字段（含 `seed`）以最终 Bot 值为准。Bot 的 `strict_features` 固定为 false，并记录模型未覆盖信息。独立 HTTP 服务只读 reward 配置或其 `--config` 覆盖文件，不读取 bot-policy。修改后重启相应进程。

每次 Bot 运行报告目录保存 `policy-config.json` 与 `reward-config.json`，后者是合并后的实际评分配置。检查这两份快照可避免误看另一目录的文件。`seed` 是策略采样种子；`--seed` 是游戏种子，两者独立。

## 预测目标与权重

短期：弱怪池阶段使用当前幕弱普通怪池（第一幕前 3 次、后续幕前 2 次普通战斗）；之后用可见地图的近期战斗窗口。通常看下两层；若两层均无可能战斗，沿可见地图延伸到第一个可能战斗层。没有可达战斗则为空，不虚构敌人。商店、篝火等不计入平均分母；问号战斗概率同时计入战损和有效战斗次数。`short_reduction=mean` 是按可能战斗的平均，`sum` 是加权总损失。

长期目标在同一次决策的所有候选间保持一致：

1. 每幕第 0–6 层（上限由 `boss_target_after_act_floor` 控制），先用未拿牌的当前构筑估计精英风险。当前 HP 减近期预期总损失、目标精英损失后，仍严格高于 `elite_safety_margin`，则面向 Boss；否则面向精英。
2. 第 7 层起强制面向 Boss，不再用精英风险切换。
3. 本幕最后一个 Boss 战后，短期看下一幕弱普通怪，按下一幕第 0 层重新判断精英或 Boss。下一幕 Boss 尚不可见时使用公开 Boss 池均值，不读取未来实际 Boss。
4. 已公开的双 Boss 分别预测，长期评分逐构筑取掉血较多者；生存预算累计两场。第一场打完后只剩第二场；最终通关无未来评分。

长短期权重也用未改变的当前构筑统一判断：当前 HP 减近期总损失和长期目标损失后，严格高于该目标的安全余量，则使用 `short_weight/long_weight`；否则使用 `weak_short_weight/weak_long_weight`。已出现在短期窗口的同一目标战斗会去重。预算不乘评分权重，不使用 rollout 假想牌组，也不计假想回血或药水收益。

当前完整输入不再以“近期掉血 >10/20”切权重。`short_strength_loss_threshold` 和 `elite_target_loss_threshold` 仅供缺少 HP 的旧输入兼容，日志明确标识兼容路径。旧 `crisis_boss_loss_fraction` 已退役，加载时警告并忽略。

## 搜索、危机与拿牌门槛

| 场景 | 深度 |
| --- | --- |
| `context.postCombat=true` 的战后奖励 | `reward_rollout_depth`，允许 3/4/5；危机加 `crisis_extra_depth`，总深度不超过 6；临近 Boss 也不缩短 |
| 商店、事件选牌、删牌、升级 | `depth_schedule` 决定基础深度，受 `max_rollout_depth` 和剩余层数限制 |
| 非固定深度的跨幕评估 | `post_boss_rollout_depth`；危机可加深，总深度不超过 6，不受已结束幕的距离 0 限制 |
| 最终通关 | 0 |

普通每个父节点采样 `samples_per_parent`，保留 `keep_per_parent`；危机用 `crisis_samples_per_parent/crisis_keep_per_parent`。每个根候选深度 n 留 K^n 个末端，计算量随宽度和深度迅速增长。以输出的 `stats.per_depth` 为准。`lookahead_pairs` 允许以两步配合来比较保留分支。

这里的 **crisis 与血量预算不足是两个独立判断**：先做普通 rollout，所有候选中最好的长期混合预期掉血，严格超过 `crisis_boss_loss_threshold` 才触发危机。名字保留历史的 boss，但目标也可能是精英。日志 `crisis_basis`、`crisis_target_room`、`projected_long_loss` 明确记录口径。危机扩大搜索并改变拿牌门槛，不直接替代权重判断。

可跳过选牌时，卡牌综合分必须严格超过跳过分加 `normal_card_min_gain`；危机使用 `crisis_card_min_gain`。强制选择没有虚构的跳过按钮。商店比较相对不买牌的增益，再扣金币代价，每次购买后重评。

## Rollout 信息边界

只从模型支持的普通静默猎手卡池独立采样。白/蓝/金的类别概率默认 9:5:1，类别内等概率。不读游戏 RNG、未来奖励列表、未知房实际内容；当前已展示的候选属于合法输入。卡池、重复概率和稀有度是假设，不是原游戏后续发牌的精确概率模型。

每个父节点除采样拿牌和跳过，还可提供一条最好的升级候选，与其他分支竞争保留名额。`rollout_max_upgrades` 控制每条路径允许升级几次，一次升级占一层；`upgrade_probability` 则是抽到升级版新牌的概率，两者不同。升级未按真实篝火数量和休息代价约束，不保证能实现。

最终前 `leaf_top_fraction` 和后 `leaf_bottom_fraction` 两组按各自权重混合，组内受 `leaf_rank_power` 影响；较差组最差者排名权重最大。两组来自**已经择优保留的路径**，后 25% 不是所有可能未来的最差 25%，也不是无偏期望。小集合可能重叠，重叠贡献相加。

模型以满血、无药、8 秒战斗求解标签训练。预算是启发式，不能解释为当前血量下的死亡概率。跨幕沿用当前库存，不假设下一幕先古遗物或回血。其余已知近似及本轮整理边界见 [整理记录](policy-cleanup-20261102.md)。
