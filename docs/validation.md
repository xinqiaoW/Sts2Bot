# 验证与审计边界

## 标签验收

任务须为数据库 `complete`，结果状态与排队教师匹配，且 `combatEnded`、observation 的 `complete` 均为真：

| 后端 | 完成状态 | 额外身份校验 |
| --- | --- | --- |
| 原生 Wine | `Passed` | 原生教师与 runtime 的冻结摘要 |
| 独立模拟器 | `StandaloneCompleted` | 游戏、求解器、宿主、解锁状态、进度快照及 run ID / 种子 / 目标 |

模拟器还须保留 `isolated-experiment`、`productionValidated=false`、`productionReady=false`、`productionLabels=false`。通过入库或导出校验不等于模拟器已完成生产等价验证，详见[模拟器采集](simulator-collection.md)。后端身份由 `damage_model/provenance.py` 核对。

实际初始卡牌、遗物顺序及计数、目标和教师须与请求一致。`damage_model/observation.py` 逐张核对升级、附魔和持久状态，协议 3 缺少实际状态回读即拒绝。异常、超时、清理期限错误和隔离任务不进入标签。

生命值必须为整数、满血开战，终局 HP 在合法边界内，`netHpLoss = initialHp - finalHp`，死亡标记与 HP=0 一致。标准化战斗起始 70/70，回血抵消净掉血。最大生命下降只接受已适配的单只咬人卷轴弱/普通编组，或初始牌组含至亮之焰的模式；下降须为偶数或触及最小值 1。这是机制模式校验，尚不是逐事件追踪，也不表示支持任意改血机制。

## 测试与报告范围

Python 测试覆盖来源还原、计数与先古合法性、特殊卡状态、队列租约/去重/原子写入、重试隔离、备份、谱系及训练划分。模拟器相关测试另覆盖发布包身份、进程回收、后端结果验收与导出。原生烟测和差分验证游戏恢复与终局；少量场景通过不能证明全部组合正确。

固定训练报告与实验见[训练文档](../train/README.md)，RunController 的固定原生验收见[整局验收](run-controller-validation.md)。这些记录只证明对应版本和输入的覆盖，不是当前分支重新执行的结果。留出误差也不能证明最优搜索或未见内容的全量正确性。

## 运行与证据检查

核对对应实例或执行副本的版本、冻结教师、实际进程与锁、近期有效产出、备份摘要和 SQLite quick_check。采集及补采操作分别见[持续采集](continuous-collection.md)和[补采工具](../tools/one_off/README.md)。

部署副本的 `evidence/` 保存历史原生验收与故障附件，通常不随 checkout 提供；它的迁移、监控脚本不自动覆盖新增数据库或模拟器配置。部分旧失败附件有缺口，明细保存在部署证据 `evidence/reconnect-20260913-1309/missing-native-artifacts.json`。数据库中的失败记录与隔离状态保留，缺失附件不以重打结果替代。有效标签、去重索引和附件完整性须分别核验。
