# 静默猎手预期掉血模型

目标：`F(真实卡组及升级、逐张附魔, 遗物及采样计数, 原版怪物编组) → 标准化预期净掉血`。

当前采集流程为 **Spire Codex `.run` → 还原战前构筑 → 校验 → CombatSolver 独立对战**。真实任务优先；队列耗尽时，使用已验证真实构筑的一代小／大变异补充巢穴和荣耀任务，小变异 60%、大变异 40%，不通过人工评分筛选父代。遗物计数按用户要求在已验证的合法范围内随机采样，记录采样种子；同一输入的四次对战固定计数，只改变战斗种子。详见[变异规则](docs/mutations-8s.md)。

原版 0.111.0，静默猎手，单人标准模式，A10，70/70 满血开战，无药水。最多 45 张牌、0–5 张无色牌，保留真实诅咒及支持的事件、先古牌。按用户要求移除影响最大生命的遗物，保留其余构筑和真实历史；不因该遗物直接拒绝整套输入。复活、棱彩宝石及尚未适配的其他持久状态仍排除。保留回血遗物。真实构筑只测试同一 `.run`、同幕出现楼层前后各两层实际遇到的原版编组，重复出现时合并范围；变异构筑沿用父代目标。每场独立开战，不把前一场的损失带入后一场。

掉血标签必须来自原版完整终局：初始满血减去最终生命，包含回血抵消，死亡另记布尔标签。超时和异常没有掉血标签。真人的掉血、胜负和用药记录只保存在原始来源中，不用作老师标签，也不用于挑选“好构筑”。

## 使用

当前在 01 的 `/data2/pl/ImageTask/wxq/Projects/Sts2Bot` 采集，Python `.venv/bin/python`；本地代码 `C:\Users\www\Documents\Sts2DamageModel`。活动状态以 `data/collection-session.json` 和 `data/active-collection.json` 为准。用户授权持续采集直到明确要求停止，每半小时巡检。原租用机操作保留在[历史记录](docs/rental-collection.md)。

当前批次见 [8 秒搜索](docs/search-8s.md)，运行环境见[切回 01](docs/return-to-01.md)。

```bash
.venv/bin/python -m damage_model.cli import-runs --directory data/external/local-runs
.venv/bin/python -m damage_model.cli sync-runs
.venv/bin/python -m damage_model.cli status
.venv/bin/python -m damage_model.cli work --runtime configs/runtime-wine-pilot.json --limit 256
```

上面的裸命令仍使用 CLI 历史默认值（v2、2 秒配置）；操作当前批次时，必须在子命令之前显式传入 `--db data/collection-real-runs-v3.sqlite --config configs/real-runs-8s.json`。变异另库存储于 `data/collection-mutations-v1.sqlite`。`configs/teacher.json` 冻结原版、CombatSolver 和 RitsuLib 摘要；当前 8 秒短搜、Medium、DOP 1。老师代表该搜索预算下的实际表现，不保证最优打法。

持续采集由 `tools.collect_continuous --collect-only` 管理：提前补充真实来源，队列低于水位时下载下一页；通过 `--mutation-db` 启用真实队列耗尽后的变异补充。每个 worker 使用独立 Wine prefix，启动和停止方式见[持续采集](docs/continuous-collection.md)，当前参数以活动会话为准。

## 来源与校验

导入器先从初始牌组（含进阶之灾）依次应用升级、删牌、变牌、获得牌和遗物记录。战前快照取在该层奖励之前。重复牌升级和同层操作顺序不确定时保留一致解释，最终与 `.run` 的牌组及遗物顺序核对；不能确认的状态不进队列。附魔 ID、数值与具体卡牌升级状态共同保留，并与原生开战观察逐张核对。混合事件/战斗房间及其他未适配持久字段仍明确跳过，原始记录和原因保留。

当前导入修订为 `shared_ancient_provenance_v5`，已补齐达弗在第二或第三幕、同局最多一次的共享先古来源。训练观察协议仍为 2，同一冻结老师的 v3 活动库内追加新接受的输入，旧 jobs/results/attempts 不重写，旧导入报告存入 `source_import_history`。模型编码包含卡牌 ID × 升级 × 附魔类型的数量、数值和平方和；原始输入保留每一张牌，旧模型遇到新增特征会明确拒绝。

已验证的一次性遗物直接装入，不重放获得时的删牌、升级或奖励效果。珠宝盒、涅奥的苦痛、古老牙齿已适配，以保留神化、涅奥之怒和压制；古老牙齿的两个保存字段仅供原版提示文字使用，牌组变化已在历史中还原。不同来源的相同输入共享对战任务，`build_origins` 保留每份 `.run`、楼层和移除遗物清单；`source_runs` 保留原始内容、来源 URL、摘要和导入报告。公开导出页保留 gzip、摘要和下一页游标，完整下载和导入后才推进游标。其他待适配项见[遗物清单](docs/unadapted-relics-20260906.md)。

训练读取数据时按“源局与共享构筑的连通组”划分训练、验证和测试集，防止同一局流入多个集合。数据持续扩充可能合并连通组，因此每次训练应使用独立一致性快照；若没有足够的独立留出组，训练会拒绝，不能伪造评估隔离。

```bash
# 在具备 PyTorch 的训练环境中，对固定快照训练。
python -m damage_model.cli --db data/training-snapshot.sqlite train --output checkpoints/real-runs
```

目前 01 只采集，首版 `checkpoints/v1` 保留。旧随机数据 `data/collection-horizon.sqlite` 和更早 `data/collection.sqlite` 不删除、不与新数据静默合并；`configs/v1.json` 保留为旧数据与兼容测试的历史配置。最早的随机构筑代码 `sampling.py`、旧轮次驱动 `collect_rounds.py`、`seed/evolve` 命令已移除。Build 的代数、父代等字段同时用于历史数据兼容和当前真实构筑变异的血缘记录。

更多边界及实测记录见 [真实局导入](docs/spire-codex-run-assessment.md)。
