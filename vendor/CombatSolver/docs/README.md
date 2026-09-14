# 内嵌 CombatSolver 文档范围

此目录保留求解器 Mod 的架构、测试、开发和版本资料。它们不定义外层 Sts2Bot 的训练输入白名单、来源版本、运行目录或采集参数；这些见[项目入口](../../../README.md)、[搜索配置](../../../docs/search-8s.md)与[遗物规则](../../../docs/relic-rules.md)。

Mod 支持的药水、角色和玩家默认 NoGC/并行度，与当前静默、无药水、NoGC 关闭、DOP 1 的采集配置不同。“支持实体”“有差分证据”和“允许作为标准化初始输入”也是不同条件。

## 维护入口

| 资料 | 用途 |
| --- | --- |
| [Mod README](../README.md) | 本副本玩家功能、安装和设置 |
| [架构地图](ARCHITECTURE.md) | 当前源码职责与所有权边界 |
| [测试矩阵](TEST_MATRIX.md)、[适配验证](ADAPTATION_VERIFICATION.md) | 可重跑场景、验收方法与各次测试记录 |
| [开发笔记](DEVELOPMENT_NOTES.md)、[策略记录](STRATEGY_OPTIMIZATION_LOG.md) | 已有实现、未发布变化和未来设想，需按章节版本区分 |
| [重构路线](refactoring/refactor-roadmap.md) | 重构边界和已完成批次 |
| [引擎来源](../src/Engine/README.md)、[第三方声明](../THIRD_PARTY_NOTICES.md) | 代码来源与许可条件 |

## 历史资料的读法

`*-RELEASE_NOTES.md`、带日期的审计、`issues/`、`strategy/`、性能和 UI 修复报告记录当时问题、环境和验证结果，保留用于定位回归；不是当前待办清单或生产恢复指令。文中的“当前”“已通过”和稳定版号均受报告版本/日期限制，不代表重新核验过上游最新发布。

[早期未适配实体报告](../STS2_UNADAPTED_FEATURES_AUDIT.md) 基于求解器 0.6.0；[钩子覆盖目录](COMBAT_HOOK_COVERAGE.md) 是 0.15.0 生成快照，不手改其统计。两者不能当作现有采集器的缺口清单。静态条目数也不能证明全组合战斗等价；判断现行能力需核对实际源码、教师与对应测试证据。

外层采集文档删除了重复恢复流水账；这里的原始问题、版本说明、测试证据、AGENTS/skills 和第三方声明继续保留。此次文档审核不修改求解器、重新生成覆盖表或重跑原生战斗。
