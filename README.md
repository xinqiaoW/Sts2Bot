# 静默猎手预期掉血模型

目标：`F(卡组及逐张升级、附魔、持久状态，遗物及计数，原版怪物编组) → 预期净掉血`，并预测死亡概率。

数据流程：**Spire Codex `.run` → 还原并标准化战前构筑 → CombatSolver 独立对战 → 有效终局标签 → 冻结快照训练**。真实来源与真实构筑的一代变异分别采集，不按真人胜负或人工评分筛选强构筑。

## 采集规则

| 项目 | 设置 |
| --- | --- |
| 代码维护 | SSH `01`，`/data2/pl/ImageTask/wxq/Projects/Sts2Bot` |
| 执行与数据 | `/data1/pl/ImageTask/wxq/Projects/Sts2Bot` |
| 来源版本 | v0.109.0 / v0.109.1、v0.110.0 / v0.110.1、v0.111.0 |
| 实际战斗 | 游戏 0.111.0，静默猎手，单人标准 A10，70/70 满血，无药水 |
| 搜索 | Medium、short_only、8,000 ms、DOP 1，整场期限 120 秒 |
| 战斗种子 | 专项目标名单内每个构筑–编组 24 个，其余 4 个 |
| 正常采集库 | `data/collection-real-runs-v4.sqlite`、`data/collection-mutations-v2.sqlite`、`data/collection-targeted-mutations-v1.sqlite` |
| 三队列调度 | 真实/普通变异/专项变异按领取次数 2:1:1；空队列允许借用 |

并发数、运行状态、资源参数和备份路径以执行副本的配置、进程及状态文件为准，见[持续采集](docs/continuous-collection.md)。历史种子补采使用独立队列，只消费已有构筑的补采任务，见[补采工具](tools/one_off/README.md)。

0.109 来源中的恫吓转换为侧步，保留升级、附魔及可还原状态；旧版本只提供输入，标签统一重新用 0.111.0 生成。完整规则见[来源版本与调度](docs/source-versions-and-scheduling.md)。

最多 45 张牌、0–5 张无色牌；允许真实永久牌组中的诅咒、事件/先古牌、任务牌、状态牌和衍生牌。最大生命遗物及明确指定的 13 件遗物单独移除，保留剩余构筑和来源历史；回血遗物保留。其他角色永久牌、棱彩宝石、万花筒和未适配状态仍按规则拒绝。详见[卡牌状态](docs/card-state.md)、[遗物规则](docs/relic-rules.md)。

新真实构筑匹配同一 `.run`、同一幕来源楼层前后各两层实际遇到的原版编组。正常持续采集按构筑 ID 去重：已存在的构筑不再增加编组或种子任务。43 个专项目标由 `configs/mutations-targeted-8s.json` 定义，真实、普通变异和专项变异共用 24/4 种子规则；每场独立重置。普通变异沿用父代目标，以荣耀 60%、巢穴 40%，小变异 60%、大变异 40% 生成；专项变异按编组均衡生成，详见[变异规则](docs/mutations-8s.md)和[专项采集](docs/targeted-mutations.md)。

## 操作入口

以下命令在 01 的执行目录查看正常真实库状态：

```bash
cd /data1/pl/ImageTask/wxq/Projects/Sts2Bot
.venv/bin/python -m damage_model.cli \
  --db data/collection-real-runs-v4.sqlite --config configs/real-runs-8s.json status
```

查看其他正常库或补采库时，显式替换 `--db`。不要省略 `--db`、`--config`：CLI 默认值仍指向 v2 库和 2 秒配置。源码与运行副本分开维护，切换 Git 分支不会部署代码或重启进程，见[运行环境](docs/runtime.md)。

正常采集控制器使用 `--collect-only`，不自动训练、不覆盖 `checkpoints/v1`。独立的多模型训练、比较、推理与评估工具见 [train/README.md](train/README.md)。默认训练配置尚未纳入专项库和补采库；训练前须显式选择完整来源并导出冻结快照。

## 标签与数据边界

标签为原版完整终局的 `initialHp - finalHp`，回血会抵消损失，死亡另记布尔值；超时、异常和不完整终局不产生标签。有效种子的均值是该搜索预算下的预期掉血估计，仍有采样误差，不保证最优打法。真人掉血与用药记录保存在原始来源中，不充当标签。

构筑、来源、遗物计数种子、教师和全部尝试分别留档；跨库训练按源局与共享构筑/变异血缘的连通组划分，避免泄漏。旧协议标签不改写成新协议；训练只能按显式兼容规则合并。已知数据限制见[验证与审计](docs/validation.md)。

## 文档导航

| 内容 | 入口 |
| --- | --- |
| 导入与目标范围 | [真实局导入](docs/spire-codex-run-assessment.md) |
| 版本转换、历史来源回补、三队列调度 | [来源版本与调度](docs/source-versions-and-scheduling.md) |
| 运行、停止、备份、故障恢复 | [持续采集](docs/continuous-collection.md)、[运行环境](docs/runtime.md) |
| 历史构筑增加战斗种子 | [一次性补采](tools/one_off/README.md) |
| 搜索预算与教师边界 | [8 秒搜索](docs/search-8s.md) |
| 卡牌与遗物状态 | [卡牌状态](docs/card-state.md)、[遗物规则](docs/relic-rules.md)、[计数范围](docs/counter-state.md) |
| 一代变异 | [普通变异](docs/mutations-8s.md)、[专项变异](docs/targeted-mutations.md) |
| 数据页面及支持范围 | [查看与刷新](docs/data-viewer.md) |
| 验证及已知限制 | [验证与审计](docs/validation.md) |
| 模型训练和报告 | [训练入口](train/README.md) |
| 内嵌求解器资料 | [文档范围](vendor/CombatSolver/docs/README.md) |

整局环境 `runctl.RealRunEnv` 用 `reset/step` 控制地图选择，CombatSolver 执行战斗，局外规则由原版处理。范围与限制见 [RunController](docs/run-controller.md)，命令见 [运行入口](runctl/README.md)。已退役的拟合式模拟器见[归档说明](docs/历史垃圾箱/sim-v0-fitted/README.md)。
