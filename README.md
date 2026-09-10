# 静默猎手预期掉血模型

目标：`F(真实卡组及升级、逐张附魔, 遗物及采样计数, 原版怪物编组) → 标准化预期净掉血`。

当前采集流程为 **Spire Codex `.run` → 还原战前构筑 → 校验 → CombatSolver 独立对战**。遗物计数按用户要求在已验证的合法范围内随机采样，记录采样种子；同一输入的四次对战固定计数，只改变战斗种子。

原版 0.111.0，静默猎手，单人标准模式，A10，70/70 满血开战，无药水。最多 45 张牌、0–5 张无色牌，保留真实诅咒及支持的事件、先古牌。按用户要求移除影响最大生命的遗物，保留其余构筑和真实历史；不因该遗物直接拒绝整套输入。复活、棱彩宝石及尚未适配的其他持久状态仍排除。保留回血遗物。每套构筑只对当前幕的原版怪物编组逐个独立测试，不把前一场的损失带入后一场。

掉血标签必须来自原版完整终局：初始满血减去最终生命，包含回血抵消，死亡另记布尔标签。超时和异常没有掉血标签。真人的掉血、胜负和用药记录只保存在原始来源中，不用作老师标签，也不用于挑选“好构筑”。

## 使用

项目 `/data2/pl/ImageTask/wxq/Projects/Sts2Bot`，Python `.venv/bin/python`。采集在本机 01 上持续运行，直到明确要求停止。当前批次见 [8 秒搜索](docs/search-8s.md)，运行环境见 [切回01](docs/return-to-01.md)。

```bash
.venv/bin/python -m damage_model.cli import-runs --directory data/external/local-runs
.venv/bin/python -m damage_model.cli sync-runs
.venv/bin/python -m damage_model.cli status
.venv/bin/python -m damage_model.cli work --runtime configs/runtime-wine-pilot.json --limit 256
```

当前活动库和配置以 `data/collection-session.json`、`data/active-collection.json` 为准；现行为 8 秒批次 `data/collection-real-runs-v3.sqlite` / `configs/real-runs-8s.json`。旧 v2 库与 2 秒配置 `configs/real-runs.json` 保留，不再领取。`configs/teacher.json` 冻结原版、CombatSolver 和 RitsuLib 摘要；老师代表该搜索预算下的实际表现，不保证最优打法。

持续采集由 `tools.collect_continuous --collect-only` 管理：提前补充真实来源，队列低于水位时下载下一页；没有新来源时等待，不回退到随机生成。每个 worker 使用独立 Wine prefix，启动和停止方式见 [持续采集](docs/continuous-collection.md)。

## 来源与校验

导入器先从初始牌组（含进阶之灾）依次应用升级、删牌、变牌、获得牌和遗物记录。战前快照取在该层奖励之前。重复牌升级和同层操作顺序不确定时保留一致解释，最终与 `.run` 的牌组及遗物顺序核对；不能确认的状态不进队列。附魔 ID、数值与具体卡牌升级状态共同保留，并与原生开战观察逐张核对。混合事件/战斗房间及其他未适配持久字段仍明确跳过，原始记录和原因保留。

当前导入修订为 `max_hp_relic_normalization_v3`，训练观察协议仍为 2。同一冻结老师、同一个活动库内追加新接受的输入，旧 jobs/results/attempts 不重写，旧导入报告存入 `source_import_history`。原生搜索仍基于 33babbe，7ba49f9 只增加训练观察中的附魔字段。模型编码包含卡牌 ID × 升级 × 附魔类型的数量、数值和平方和；原始输入保留每一张牌，旧模型遇到新增特征会明确拒绝。

已验证的一次性遗物直接装入，不重放获得时的删牌、升级或奖励效果。珠宝盒、涅奥的苦痛、古老牙齿已适配，以保留神化、涅奥之怒和压制；古老牙齿的两个保存字段仅供原版提示文字使用，牌组变化已在历史中还原。不同来源的相同输入共享对战任务，`build_origins` 保留每份 `.run`、楼层和移除遗物清单；`source_runs` 保留原始内容、来源 URL、摘要和导入报告。公开导出页保留 gzip、摘要和下一页游标，完整下载和导入后才推进游标。其他待适配项见[遗物清单](docs/unadapted-relics-20260906.md)。

训练读取数据时按“源局与共享构筑的连通组”划分训练、验证和测试集，防止同一局流入多个集合。数据持续扩充可能合并连通组，因此每次训练应使用独立一致性快照；若没有足够的独立留出组，训练会拒绝，不能伪造评估隔离。

```bash
# 在具备 PyTorch 的训练环境中，对固定快照训练。
python -m damage_model.cli --db data/training-snapshot.sqlite train --output checkpoints/real-runs
```

本机只采集，不覆盖首版 `checkpoints/v1`。旧随机数据 `data/collection-horizon.sqlite` 和更早 `data/collection.sqlite` 不删除、不与新数据静默合并；`configs/v1.json` 仅保留为旧数据的历史配置。随机构筑代码 `sampling.py`、旧轮次驱动 `collect_rounds.py`、`seed/evolve` 命令已移除。Build 中旧代数、父代等字段仅用于兼容历史数据展示。

更多边界及实测记录见 [真实局导入](docs/spire-codex-run-assessment.md)。
