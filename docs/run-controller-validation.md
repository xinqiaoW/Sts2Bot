# RunController M1 原生验收（2026-09-15）

本页保留固定版本的验收范围，不表示当前分支重新执行过这些测试。设计见 [RunController](run-controller.md)，运行命令见 [runctl/README.md](../runctl/README.md)。

验证在 01 的独立目录 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot-runctl-pilot` 进行，原版 Windows 0.111.0 经 Wine headless 执行；游戏、Mod 和 prefix 与正式采集隔离。请求、动作、逐层日志、终局快照和失败现场保存在试验目录，不加入 F 训练库。

## 构建与协议

- .NET 9 Release 构建及 PowerShell 架构门禁通过；引用与试验运行时一致的冻结游戏程序集。
- Python 客户端 16 项测试通过，覆盖连续 reset/step、ID/序号隔离、非法动作、独占目录、失败结果、退出、超时现场和关闭失败后的锁保留。
- 原生协议检查 7/7 通过：错误 run ID、过期序号、越界、缺少 `choice` 和等待动作超时均明确失败；旧单场 `SMOKE-001` 在同一原生进程内两次 Passed。
- 证据：`validation/reports/protocol/protocol.json`、`validation/pytest-final.log`。

## 整局覆盖

| 验证批次 | 完整对局 | 完整战斗 | 证据目录 |
| --- | ---: | ---: | --- |
| 初始整局验证 | 2 | 20 | `reports/smoke-v2/` |
| 动作校验及界面停滞保护 | 4 | 26 | `reports/smoke-v3/` |
| 最终地图过渡等待版本 | 2 | 14 | `validation/reports/final/` |

累计 8 次整局试跑、60 场战斗，包括 6 个不同游戏种子及其中 2 个在最终构建上的复跑；最终 DLL 的整局证据是表中最后一批。各批报告目录及对应 `combat_solver_runs/<runId>/` 保留逐局身份、耗时和状态，最终批次的汇总与审计为 `summary.json` 和 `audit.json`。

已覆盖捏奥开局、地图选择、普通/精英/Boss 战斗、战后奖励、事件、商店、篝火、附魔选择界面、第一幕到第二幕转换，以及自然死亡后在同进程重开。整局保留原生 HP 与最大生命变化，不套用单场采集的满血重置。

验收检查事件序号、run ID、A10/捏奥标识、合法 HP、战斗开始/结束配对和终局快照。完成结果在返回菜单并完成静稳检查后发布；新局使用新 ID 和决策序号。失败请求不计作自然死亡，中止尝试不计入完成数量。

## 尚未覆盖

这些证据证明控制链可运行，不证明策略强度或所有内容均已验收。第三幕、胜利终局、全部特殊事件及事件内战斗组合仍需补充原生验证。

本版只有地图动作交给 Python，局外策略为固定基线，战斗禁用药水。尚未执行长期 20 局稳定性验收，也未完成原生 Windows 可见 UI 验收；现有场次不足以估计胜率或 F 偏差。
