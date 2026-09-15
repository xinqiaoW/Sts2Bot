# 静默猎手预期掉血模型

目标：`F(卡组及逐张升级、附魔、持久状态，遗物及计数，原版怪物编组) → 预期净掉血`，并预测死亡概率。

数据流程：**Spire Codex `.run` → 还原并标准化战前构筑 → CombatSolver 独立对战 → 有效终局标签 → 冻结快照训练**。真实来源与真实构筑的一代变异并行采集，不按真人胜负或人工评分筛选强构筑。

## 当前生产口径

| 项目 | 设置 |
| --- | --- |
| 采集主机与目录 | SSH `01`，`/data1/pl/ImageTask/wxq/Projects/Sts2Bot` |
| 来源版本 | v0.109.0 / v0.109.1、v0.110.0 / v0.110.1、v0.111.0 |
| 实际战斗 | 游戏 0.111.0，静默猎手，单人标准 A10，70/70 满血，无药水 |
| 搜索 | Medium、short_only、8,000 ms、DOP 1，整场期限 120 秒 |
| 并发 | 25 个独立运行环境：20 个优先真实，5 个优先变异；空队列允许互相借用 |
| 活动数据库 | `data/collection-real-runs-v4.sqlite`、`data/collection-mutations-v2.sqlite` |
| 运行与备份 | 持续采集直到用户停止；运行内存预留 0；新 worker 启动预算 2 GiB；两路 300 秒双槽备份 |

0.109 来源中的恫吓转换为侧步，保留升级、附魔及可还原状态；旧版本只提供输入，标签统一重新用 0.111.0 生成。完整规则见[来源版本与调度](docs/source-versions-and-scheduling.md)。

最多 45 张牌、0–5 张无色牌；允许真实永久牌组中的诅咒、事件/先古牌、任务牌、状态牌和衍生牌。最大生命遗物及明确指定的 13 件遗物单独移除，保留剩余构筑和来源历史；回血遗物保留。其他角色永久牌、棱彩宝石、万花筒和未适配状态仍按规则拒绝。详见[卡牌状态](docs/card-state.md)、[遗物规则](docs/relic-rules.md)。

真实构筑匹配同一 `.run`、同一幕来源楼层前后各两层实际遇到的原版编组；每目标 4 个种子，每场独立重置。同一构筑重复出现时合并目标范围，已有任务去重。变异沿用父代目标，以荣耀 60%、巢穴 40%，小变异 60%、大变异 40% 生成，详见[变异规则](docs/mutations-8s.md)。

## 操作入口

以下命令在 **01 的现行生产目录**执行。活动路径与参数以 `data/collection-session.json`、`data/active-collection.json` 和实际进程为准。

```bash
cd /data1/pl/ImageTask/wxq/Projects/Sts2Bot
.venv/bin/python -m damage_model.cli \
  --db data/collection-real-runs-v4.sqlite --config configs/real-runs-8s.json status
```

不要省略 `--db`、`--config`：CLI 的历史默认值仍指向 v2 库和 2 秒配置。旧 `/data2` 仓库不是当前采集目录，不能从那里恢复服务。Git 工作副本与运行副本分开；当前分支尚未包含全部线上兼容版本和双队列调度代码，不能把 checkout 或单独同步文档当作生产部署，详见[运行环境](docs/runtime.md)。

采集控制器使用 `--collect-only`，不自动训练、不覆盖 `checkpoints/v1`。仓库已经有独立的多模型训练、比较、推理与评估工具和两批固定快照报告，见 [train/README.md](train/README.md)。训练需要另行准备完整、一致的来源快照。

## 标签与数据边界

标签为原版完整终局的 `initialHp - finalHp`，回血会抵消损失，死亡另记布尔值；超时、异常和不完整终局不产生标签。四种子均值是该搜索预算下的预期掉血估计，不保证最优打法。真人掉血与用药记录保存在原始来源中，不充当标签。

构筑、来源、遗物计数种子、教师和全部尝试分别留档；跨库训练按源局与共享构筑/变异血缘的连通组划分，避免泄漏。旧协议标签不改写成新协议；训练只能按显式兼容规则合并。已知历史附件缺口与冻结批次位置见[验证与审计](docs/validation.md)。

## 文档导航

| 内容 | 入口 |
| --- | --- |
| 导入与目标范围 | [真实局导入](docs/spire-codex-run-assessment.md) |
| 版本转换、历史回补、20/5 调度 | [来源版本与调度](docs/source-versions-and-scheduling.md) |
| 运行、停止、备份、故障恢复 | [持续采集](docs/continuous-collection.md)、[运行环境](docs/runtime.md) |
| 搜索预算与教师边界 | [8 秒搜索](docs/search-8s.md) |
| 卡牌与遗物状态 | [卡牌状态](docs/card-state.md)、[遗物规则](docs/relic-rules.md)、[计数范围](docs/counter-state.md) |
| 一代变异 | [变异规则](docs/mutations-8s.md) |
| 数据页面 | [查看与刷新](docs/data-viewer.md) |
| 验证及已知限制 | [验证与审计](docs/validation.md) |
| 模型训练和报告 | [训练入口](train/README.md) |
| 内嵌求解器资料 | [文档范围](vendor/CombatSolver/docs/README.md) |

强化学习环境的第一版已接入真实游戏：`runctl.RealRunEnv` 用 `reset/step` 控制地图选择，CombatSolver 执行战斗，局外规则由原版处理。范围与限制见 [RunController](docs/run-controller.md)，命令见 [运行入口](runctl/README.md)。早先的拟合式抽象模拟器已退役，存档在 [历史垃圾箱](docs/历史垃圾箱/sim-v0-fitted/README.md)。
