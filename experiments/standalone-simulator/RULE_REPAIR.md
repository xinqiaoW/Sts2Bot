# 2026-09-28 自动出牌选牌边界修复

v4 于 2026-09-27 14:56 CST 中止，未完成 24 小时验收，正式会话未切换。触发项是隔离面板 case-000003：Toolbox 的开局计划完成后，Whispering Earring 自动打出 Survivor。游戏临时安装自己的确定性选牌器，原生 NativeChoiceRuntime.Observe 在 CardSelectCmd.Selector 非空时直接返回；独立宿主观察器漏掉该判断，误把游戏自身的选牌当成教师计划的额外请求。

NativeImplicitChoiceObserver 现在保持相同判断。游戏选牌器、随机数、效果和教师二进制不变，也不删除状态字段或降低比较要求。旧宿主对原录像稳定失败；修复宿主通过全部 23 个检查点，终局 HP=65、MaxHP=68、回合=3 一致。

回归报告已持久保存于 `/data1/pl/ImageTask/wxq/Projects/standalone-rule-repair-20260928/evidence/regression/report.json`：52 场原生录像、2,833 个完整状态检查点全部通过；同一新增输入分别破坏完整状态和显式 Toolbox 选择的两个反例均被拒绝。该录像已加入默认 native-replay 测试集合。

`tools/run_standalone_failure_panel.py` 在独立目录诊断全部 123 个历史隔离请求。已成功的原生录像必须复用；失败录制最多三次（含历史尝试）；原生失败、宿主不一致、诊断错误分别保留。发现一个问题后继续诊断其余案例，以建立完整待修复清单；这不改变正式 rollout 遇到差异立即排空的规则。该工具不写采集队列、不发布标签、不切换生产。

此修复及小型回归不能替代最终万构筑、50 万检查点和 24 小时运行验收。新宿主还需完整证据回归及异常面板验收，当前仍不具备正式投产结论。

## 全量重放审计与诊断

持久根目录为 `/data1/pl/ImageTask/wxq/Projects/standalone-rule-repair-20260928`。修复宿主 SHA256 为 `aa28a432b05e461942abd7702aba0065afa328b80f87d19519ccba132fa90bfa`。

- `panel/status.json`：4 个原生 worker 诊断 123 个隔离输入；最终报告为 `panel/report.json`。原生失败仍不能算作通过。
- `full-replay/final-audit.json`：2026-09-29 独立审计通过，10,036 个构筑、10,036 场战斗、532,666 个完整状态检查点、80 个目标，未解决重放差异为零。9 个原生录制失败和 455 个未执行备用输入均未计入通过。原有 campaign 和旧验收报告未修改。该结论仅对应上述宿主和旧教师，不能转移到后续修改的教师发布，也不构成正式投产许可。
- `imbued-diagnostic/report.json`：缩小为 IMBUED / ABUNDANCE 和普通攻击防御牌，分别无/有 BURNING_STICKS 的原生诊断。此实验检验开局第二次选牌的来源，不计入正式验收，也不改变历史失败结果。

新增诊断和重放控制的 7 项测试及现有 rollout 17 项测试通过。测试涵盖成功录像不可替换、失败后继续诊断其他案例、原始事件篡改拒绝，以及新宿主失败不能继承旧通过状态或检查点数量。首场实际重放通过 57 个完整检查点后启动全量回放。

## 原生教师开局重复出牌修复

最小原生对照中，仅 IMBUED / ABUNDANCE 加普通攻击防御牌可完成，增加 BURNING_STICKS 也可完成；仅增加 THROWING_AXE 即复现开局两次 ChooseCard 请求、一次计划选择，最终等待玩家回合超时。证据为持久根目录 `imbued-axe-diagnosis.json` 与所链接的原始录制和日志。该失败不能计为完整战斗通过。

原版 THROWING_AXE 首张牌增加一次重放。静态调用链显示 `AutoPlayWithChoice` 未把选择传入每次 OnPlay 内部，而在自动出牌循环结束后应用一次选择；这是下一步实际/预测最小差分需要验证的修复假设。此时没有修改教师 DLL，也没有把假设标记为已修复。

候选教师已在独立源码副本中实现每次 OnPlay 内选牌，并保留来源、上下文、时机校验。未修改版对最小请求仍只产生 1 次选择并失败，候选版产生 2 次选择并完成。`teacher-choice-repair/native-check/report.json` 记录最小输入及原 case-000005 的原生完整录制和逐动作回放通过。六个行为文件已保存到原型分支；当前冻结发布与队列仍使用旧教师，候选版须另行完成相邻语义和发布验收。

相邻验证 `teacher-choice-repair/native-adjacent-check/report.json` 已完成，通过重复弃牌、消耗后复制、下一回合自动重放场景。合计五场原生战斗、170 个完整检查点匹配；教师修复及证据提交为 `393b524`。正式队列未切换。

## 路线回放差异修复

原隔离 case-000004 在自动出牌修复候选上仍出现搜索保存状态与路线回放 HP 不一致。`teacher-choice-repair/route-debug/report.json` 保存完整动作和两侧状态；诊断版捕获 133 次手牌中存在 REGRET、回合结束 listener 却无法匹配该卡实例的事件。该计数是搜索分支诊断事件，不是独立战斗或检查点通过数。

`teacher-choice-repair/route-hook-debug/report.json` 将首个引用失效定位为束缚锁链清除卡牌附着效果后的写时复制。修复为预览保存不可变原卡身份的弱键关联；旧钩子引用仍查找到当前分支包装，数值从当前预览读取。最小失败基线、连续 Fork 隔离及同名卡反例通过；case-000004 与 case-000002 的原生完整战斗和相同动作重放分别通过 139、106 个检查点。教师修复已提交 `0dd97e6`，二进制为 `02bd107d204b4c4a5b28a7d305489aa8c937b62e0cfc8104f73a3f7a96687af9`。诊断源码和二进制仍独立保存，未进入正式发布。

## 合并修复版本验证（2026-09-29）

宿主现在固定上述教师。旧录像允许的教师身份仅为原版采集教师 `1950d98…`、已验证的自动出牌修复教师 `1342fdf…` 和当前固定教师；三者的协议 3 动作/选择编码及完整状态格式未变，游戏仍固定为 `0.111.0` 的同一 SHA。该允许列表只用于原生录像来源，不放宽宿主加载的教师或游戏身份。`combined-release/reference-check/report.json` 验证三类录像逐字段重放通过、未知教师哈希拒绝，未删减比较字段或更换历史录像。

- `combined-full-replay/`：20 个重放进程验证全部历史成功录像，最终独立审计仍须达到万构筑、50 万检查点、80 个目标。
- `combined-failure-panel/`：8 个原生 worker 对同一 123 个历史隔离输入使用新教师重新录制并比较。这是显式的新教师验证代次；旧失败、旧成功录像及原诊断面板均保留，不能据新搜索路线覆盖旧证据。
- `combined-validation-launch.json` 保存宿主、教师身份与两个控制进程。新测试量只以各自报告的完整状态证据计数，原生失败不计通过。

合并验证尚未完成，24 小时试采集及正式会话均未启动。

后续试采集候选包已冻结为 `/data1/pl/ImageTask/wxq/Projects/standalone-rollout-20260929-release`，创建时完成文件清单和实际运行依赖核验。`release_tool.py create --teacher-config` 允许显式冻结候选教师，默认仍使用仓库配置；传入文件的内容写入包内 `configs/teacher.json`，由该副本生成标签身份。6 项现有发布包完整性/启动约束测试通过。仓库正式采集的 `configs/teacher.json` 未改变。

旧后端性能报告使用原教师，回退演练要求教师身份一致，因此新包必须生成自己的后端对照证据，不能直接把旧性能报告作为新版回退输入。此项及新包并发校准尚待执行。

`run_backend_comparison.py --teacher-config` 已支持显式候选教师并记录配置文件哈希；默认配置不变，已有报告一律拒绝覆盖。8 项既有后端统计/进程复用测试和新增覆盖拒绝测试通过。`combined-benchmark/prepared-command.json` 已冻结新版对照源码、6 个历史输入、源数据库快照及独立 Wine runtime；这里只完成准备，尚未运行或宣称新版性能结果。

`original-capture-failures/` 另外使用 2 个原生 worker 复测旧万构筑面板中未计入通过的全部 9 个原生失败输入。请求从旧失败录像中提取并核对原证据哈希，旧结果不改写。`combined-release/regression/` 验证旧功能回归和本轮新增语义录像，并保留错误状态/错误选择两个反例；报告尚未完成时不得将其计为通过。

## 首次抽牌与 NINJA_SCROLL（2026-09-29）

失败面板中的首回合选牌偏离定位为首次抽牌前缺失三张 SHIV。候选教师 `443eb7d5bb01d5683de1436c421ac239dd2b32905c191f1a0e83c3a901fa3ffd` 补齐原版时序，最小输入由开局完整状态不一致变为一致；原失败案例 8 的开局也一致。两场原生录制和同动作独立重放合计通过 56 个完整状态检查点及终局。

证据目录 `ninja-scroll-repair/` 保存未修复基线、候选开局比较和 `native-check/report.json`。该报告还包含一个不带 NINJA_SCROLL 的历史录制失败输入，仍然在 `wait_player_turn` 超时，因此总报告 `passed=false`；未删去此失败或扩大超时。宿主当前固定教师和正式采集配置没有切换到此候选，正在运行的全量复核仍对应 `02bd107d…`，不能算作该新增修复的最终验收。

## NOSTALGIA 当前回合历史（2026-09-29）

候选教师 `a4714059e1b0fb491079ecf96dbafaba0981e639d10c1dabd0518c6fe946a009` 修复 NOSTALGIA 跨回合累计出牌、读取 live 历史的问题；分支计数覆盖重复出牌、嵌套开始时点、回合切换、COW、状态键及 continuation。存在该 Power 时完整状态增加 `nostalgiaStarts`，不允许旧录像缺失计数被默认为通过。

`nostalgia-repair/baseline-v3/report.json` 保留未修复回合边界失败；`candidate-v4/report.json` 通过定向生命周期和字段断言。`native-check-v4/report.json` 对原失败案例 38、61 重新原生录制，同动作回放通过 47、126 个完整检查点及终局；`negative-check/report.json` 证明仅改动一个计数为 999 被拒绝。中间版本的 `native-check/report.json` 是旧字段验证，不与最终版本重复计数。

本代 `combined-failure-panel/report.json` 已完成：105/123 匹配，18 个原生失败保留。失败输入中 4 个包含 NINJA_SCROLL/TOASTY_MITTENS、10 个包含 NOSTALGIA、2 个 Soul Fysh 暴露 BOLAS 卡牌实例状态偏离、2 个 Fabricator 在结束后仍有存活敌人的断言失败。相同模型出现是分组线索，不表示每个输入均已由定向修复证明通过；最终教师还须完整重验。

`combined-full-replay/final-audit.json` 已独立审计通过：教师 `02bd107d…` / 宿主 `56180233…` 的 10,036 个构筑、532,666 个检查点、80 个目标匹配，无未解决回放差异。9 个原生失败与 455 个未执行输入不计通过。审计首次因冻结控制目录缺少 `build_panel_contract` 未执行；补齐模块搜索路径后仅继续审计，所有 10,045 个源案例均有结果。原错误日志及 `audit-recovery.json` 保留，未重跑战斗或改写录像。此旧字段版本的通过不能转移给新增 NOSTALGIA 计数的教师。

## 返手顺序与实例身份修复（开发中，2026-09-29）

- BOLAS 与 THRUMMING_HATCHET 连续返手时，待返手 HashSet 删除后重新插入会复用空槽；Fork 重建集合消除空槽，导致完整回放与分支在同名原卡/复制卡的手牌顺序上不同。原版 BeforeHandDraw 在执行 Power、遗物之前按牌堆顺序捕获卡牌监听器。
- 返手按回调前捕获的有序牌堆实例执行；状态指纹用玩家与有序牌堆索引区分具体待返手实例，避免合并同名不同实例的分支。沿用已有待返手状态及 Fork 重映射，不新增字段或放宽相等。
- 最小旧版在第二次返手失败；候选通过两个模型的连续返手、Fork 顺序及不同实例指纹断言。教师 `42a87e6a…` 对原失败案例 109 重新原生录制，同动作独立宿主通过 90 个完整检查点和第 8 回合终局；严格增量验证通过 1,819 个展开节点、8,171 次转换，路线到第 8 回合，越过原失败第 6 回合边界。这些搜索转换不计入原生检查点数量。
- 初版增量诊断宿主在 Solve 完成后序列化无关 PotionHpSaved 属性失败，已保留失败报告；修正报告字段后的宿主成功，未改教师。Release 零警告/错误，结构门禁通过，固定 8 秒、DOP1。证据 `coverage/return-to-hand-order-repair-20260929.json`，复现请求 `coverage/unattended/return-to-hand-original-109.json`。Nightmare 选择快照、终局问题及最终全量验收仍待完成。

## NIGHTMARE 选牌快照修复（开发中，2026-09-29）

- 原版 `SetSelectedCard` 立即生成卡牌快照并清除其附着效果。旧模拟保留原卡包装，等到下一回合才克隆；选牌后升级原卡会错误改变将要生成的牌。原生方法的最小对照已复现该差异，旧版明确失败。
- 选牌时冻结游戏克隆，清除快照附着效果且不改原卡。已存在 NIGHTMARE_POWER 的主线程根额外捕获内部 selectedCard；原版 Power 深克隆会清空内部数据，不能仅克隆 Power。独立快照随既有 Fork context 重映射，生成后消耗对应 Power，父/子互不影响。
- 选牌快照指纹复用现有完整卡牌状态指纹函数（移除仅供测试的命名，原算法不变），包含动态变量和私有成长值。actual/predicted Power 文本增加 `/nightmare=` 完整卡牌字段；未知/缺失快照明确失败。新增字段涉及的旧录像不能用默认值补齐，应重新原生录制。
- 候选教师 `b714041a…` 定向测试通过：原生选牌后升级对照、附着效果隔离、父/子延迟生成、已生效 Power 的根捕获、捕获后 live 模板变更隔离、消耗时点及实际状态字段。原失败案例 109 新录制通过 90 个逐动作完整状态检查点及第 8 回合终局；仅将一个隐藏快照的升级等级改为 999 的反例被状态差分拒绝。
- Release 零警告/错误，结构门禁及 CoverageCatalog `--verify-state-fields` 通过。首次候选构建因旧测试引用尚未同步改名失败，记录保留；第二版完成同步并通过。证据 `coverage/nightmare-selection-snapshot-repair-20260929.json`，隔离测试建局 `coverage/unattended/nightmare-snapshot-minimal.json`，整场复用 `return-to-hand-original-109.json`。固定 8 秒、DOP1、120 秒请求超时。
- 本项不宣称全部规则或正式采集通过。另发现回合开始效果按 Power 类别分批、遗物穿插的顺序可能不同于原版，需要单独原生最小对照；开局直接终局、FABRICATOR 验收及最终全量仍待完成。

## 原生胜利与随从终局验收修复（开发中，2026-09-29）

- FABRICATOR 原失败构筑已有原版胜利和奖励事件，但无人测试要求所有敌人死亡而失败。定向诊断保留失败：`inProgress=False`、`overOrEnding=True`，唯一存活敌人为 STABBOT，22 HP，`primary=False/secondary=True`。原版以无存活主敌人且没有阻止结束的钩子作为胜利条件；受反击死亡的 FABRICATOR 仍可在行动尾部生成随从。
- Executor 在执行前订阅原生 CombatWon，只接受当前 CombatState 对应房间的事件，并在所有返回/异常路径解除订阅。完整胜利验收先等待原版完成胜利管线，再拒绝任何存活主敌人；不能只凭敌人列表为空或血量判断成功。明确的训练死亡路径保持原判断。
- 教师 `71bd6295…` 对同一原始案例 93 重新原生录制，记录 `NativeVictory:LivingSecondaryEnemies=1`。独立宿主按该录像的动作与选择通过 60 个完整逐动作检查点，终局 HP 67/70、第 8 回合一致。Release 零警告/错误，结构门禁通过；8 秒、DOP1、120 秒请求超时未放大。
- 证据 `coverage/native-victory-terminal-repair-20260929.json`，请求 `coverage/unattended/fabricator-terminal-original-93.json`。旧失败录制保持失败，未修改成成功结果。
- 验收边界：目前最后结束回合后的标签比较仍只保证 HP、最大 HP、回合数；需要在原生 CaptureTrainingEnd 和独立宿主同一稳定终局边界增加必检完整状态，才能证明最终敌方阵容等字段一致。此项缺口、开局直接终局、回合开始混合效果顺序、最终全量与投产门禁均未完成。
