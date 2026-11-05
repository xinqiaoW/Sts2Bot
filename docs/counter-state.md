# 遗物计数与采样范围

字段与范围依据本地原版 0.111.0 `sts2.dll` 的 IL 检查；可用 `CatalogDump --inspect` 重现。
这证明原版字段与周期，不代替求解器的实际对战验证。

| 遗物 | 输入字段 | 采样范围 |
|---|---|---|
| Happy Flower | TurnsSeen | 0–2，原版每回合按 3 取模 |
| Pen Nib | AttacksPlayed | 0–9，原版 setter 按 10 取模 |
| Nunchaku | AttacksPlayed | 0–9，采样战斗等价的模 10 状态；原版保存累计数 |
| Tuning Fork | SkillsPlayed | 0–9，每第 10 张技能触发后减 10 |
| Girya | TimesLifted | 0–3 |
| Venerable Tea Set | GainEnergyInNextCombat | false / true |
| Winged Boots | TimesUsed | 0–3，3 为用尽 |
| Lava Rock | HasTriggered | false / true，已领取首次精英奖励状态 |
| Lava Lamp | TookDamageThisCombat | false，开战重置 |
| Maw Bank | HasItemBeenBought | false / true |

本页两表共列出 28 件具有明确计数/状态范围的遗物。遗物保持获得顺序。每场恢复输入状态，记录实际起始序列化状态与计数，结束后不把变化带入下一场。
存在其他保存字段、选择页面或一次性获得效果但尚无适配的遗物，单独记录为待适配，不默认为已支持。

## 其他普通计数

以下 18 件的字段与周期针对同一 0.111.0 原版 DLL 核对。循环计数使用等价余数；非循环字段抽取合法代表值，不表示人类对局中的状态概率。随机结果固定在构筑输入，不同战斗种子不重新抽计数。

| 遗物 | 输入字段 | 代表范围 |
|---|---|---|
| 白银熔炉 | TimesUsed / TreasureRoomsEntered | 0–3 / 0–2；房间数超过 2 对本次战斗等价 |
| 钓鱼竿 | CombatsSeen | 0–2；按 3 循环 |
| 摆动球 | TurnsSeen | 0–2 |
| 石之剑 | ElitesDefeated | 0–4；第五次精英胜利后替换为玉之剑 |
| 华美发束 | IsUsed | false / true；跳过获取时清空金币 |
| 五轮书 | CardsAdded | 0–4；原版保存累计数，显示及回血触发使用累计数模 5；实机评分先验证为非负 Int32 再取模，每 5 张加入永久牌组时回血 |
| 骨茶 | CombatsLeft | 0–1 |
| 余烬茶 | CombatsLeft | 0–5 |
| 开心小花？？？ | TurnsSeen | 0–4 |
| 古茶具套装？？？ | GainEnergyInNextCombat | false / true |
| 铁棒 | CardsPlayed | 0–3 |
| 金纸 | CardsExhausted | 0–4；回合结束的临时虚无计数在战前为 0 |
| 吃不完的糖 | CombatRewardsSeen | 0、1、2；首次、奇数、非首次偶数分别保留 |
| 佩尔之翼 | RewardsSacrificed | 0–1 |
| 花粉核心 | TurnsSeen | 0–3 |
| 南瓜蜡烛 | KindleCount | 0–5；可多次添火超过 5，此处为合法子集，单场能量效果等价；不再次执行获取时添火 |
| 无礼之茶 | CombatsLeft | 0–1 |
| 旺购神秘券 | CombatsFinished / GaveRelic | 0–4 / false，或 5 / true；关联采样 |

计数是标准化输入，不还原真人计数；种子写入来源记录，同一构筑在不同战斗种子下不重新采样。周期余数和代表范围不表示真人状态分布。

玩具盒的蜡制遗物身份、融化与战斗次数相互关联，仍拒绝；黄金罗盘则单独移除，保留剩余构筑。其他展示字段、获得效果和未适配状态按[遗物规则](relic-rules.md)处理。

## 实机评分输入转换

服务（`train.advisor_service`）和机器人（`runctl`）共用 `train.live_state.normalize_relic`，依据原版 0.111.0 DLL 实际机制将实机累计状态转换为模型输入范围；不写回游戏、不补缺失字段、不重放获取/回血/奖励。

| 实机字段 | 模型输入 |
| --- | --- |
| 双截棍 `AttacksPlayed` | 非负 Int32 模 10 |
| 铁棒 `CardsPlayed` | 非负 Int32 模 4 |
| 钓鱼竿 `CombatsSeen` | 非负 Int32 模 3 |
| 五轮书 `CardsAdded` | 非负 Int32 模 5 |
| 佩尔之翼 `RewardsSacrificed` | 非负 Int32 模 2 |
| 吃不完的糖 `CombatRewardsSeen` | 0 保留；正奇数映射 1，正偶数映射 2 |
| 白银熔炉 `TreasureRoomsEntered` | 非负 Int32 截到 2；保留首次及之后的判断 |
| 南瓜蜡烛 `KindleCount` | 非负 Int32 截到 5；仅对下一场战斗等价，不声称剩余场数相同 |
| 旺购神秘券 `CombatsFinished` | 非负 Int32 截到 5；`GaveRelic` 保留并继续校验关联 |
| 熔岩灯 `TookDamageThisCombat` | 必须为 bool，评分下一场战斗按原生进房重置为 false |

笔尖、开心小花、摆动球、音叉等在原生 setter 或触发结束时已经回到周期内，继续严格检查范围；次数有限的升级/使用次数不按周期取模。负数、布尔冒充整数、浮点、字符串、Int32 溢出及未知字段仍拒绝。
