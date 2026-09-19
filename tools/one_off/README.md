# 一次性补采第 5–24 个战斗种子

代码维护位置为 01 的 `/data2/pl/ImageTask/wxq/Projects/Sts2Bot`，执行和新增数据放在 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot`。本目录仅用于历史补采，生产模块不依赖它；补采结束后可删除本目录和 `tests/test_targeted_seed_backfill.py`，后续 24/4 种子采集仍正常工作。

## 后续新数据

`configs/real-runs-8s.json` 中的 `encounter_seed_policy` 直接引用 `mutations-targeted-8s.json` 的 `target_selection.targets`。名单中的 43 个编组在真实、普通变异、定向变异三条路径中均使用 24 个种子，名单外保持 4 个。引用相对采集配置所在目录解析，不依赖启动目录。其他未配置此规则的采集配置保持原行为。

种子仍是 `digest(['battle', battle_seed, index])[:16]`，索引为 0–23；原索引 0–3 和任务 ID 不变。没有修改游戏、教师、遗物计数或来源窗口。无需为了生效而重导历史来源、迁移原队列或运行本工具；按原方式重启加载新代码/配置后的持续采集即可。已排队的旧任务不会仅因重启自动扩充，属于下方补采范围。

## 历史覆盖和去重

工具读取每个输入库的 `jobs` 和 `prior_collected_inputs`，以 `(build_id, target_id, seed)` 跨库、跨适配器去重。迁移后的 real-v4 包含 real-v3 的 400,132 场完成记录索引，mut-v2 包含 mut-v1 的 60,731 场完成记录索引，并保留了对应构筑和来源/血缘；这些数量已与迁移报告核对。因此当前只需输入 `/data1` 上的 real-v4、mut-v2、targeted-v1，即覆盖五批历史采集，不需要重新读取异常磁盘上的旧库。原始标签仍保存在历史库或既有训练快照中，本工具不会重新生成或改写它们。

只扩充名单内、原索引 0–3 至少有一个 `complete` 记录的构筑–编组对。索引 4–23 中已有任意状态任务或历史记录的种子都跳过；不会重置失败、隔离、运行中任务或尝试次数。仅有 pending、没有任何完成样本的组合不属于本次已收集历史数据，报告中的 eligible_pairs 不包括它们。

原来的 4 场如果尚未全部成功，仍只追加缺少的索引 4–23，不补打原索引。`partial_original_pairs` 和 `missing_original_seeds` 明确报告这部分缺口；24 个计划种子不等于 24 个有效结果。教师按现有 protocol 2 → 3 迁移兼容规则检查：新战斗使用当前 protocol 3，旧标签不改教师，其他游戏和搜索参数必须一致。

每个输入库生成独立的 `*.backfill.sqlite`，不写原库，不复制旧结果或伪造完成状态。新库保留构筑内容、family/split、来源窗口、变异策略历史、血缘和 focus；可直接由现有 worker 读取。命令重复运行会跳过已存在的补采任务，修改 sources 顺序、种子配置或教师后应使用新的输出目录。

2026-09-19 对 `/data1` 的只读预览覆盖 1,465,102 场历史完成记录，结果见 [完整报告](preview-20260919.json)：

| 数据来源（包含旧版本索引） | 待扩充构筑–编组对 | 待追加战斗 |
| --- | ---: | ---: |
| real-v4 / real-v3 | 126,016 | 2,520,320 |
| mut-v2 / mut-v1 | 57,585 | 1,151,700 |
| targeted-v1 | 19,778 | 395,560 |
| 合计 | 203,379 | 4,067,580 |

其中 283 对原来的 4 场未全部成功，共缺 363 个有效原始种子结果。上述表格来自最初预览。补采曾按用户要求停止，保留 1,893 场完成结果；独立复核后用户明确要求恢复，目前已按原 25 worker 配置恢复启动。停止记录和恢复授权分别保存在运行目录的 `user-stop.json` 与 `resume-*/authorization.json`。

### 数量口径

构筑数、构筑–编组对数、战斗数必须分别报告。例如一个构筑在历史记录中与两个名单内编组各打过四个种子，它是一个构筑、两个组合、八场旧战斗，需要新增四十场。工具只扩充历史已完成的组合，不对每个构筑与全部 43 个编组做笛卡尔积。

报告增加 `stored_unique_builds`（输入库中全部唯一构筑，含未完成任务）、`eligible_builds`（至少一个组合符合补采条件的唯一构筑）、`eligible_pairs`、`eligible_pairs_per_build`。各来源按跨库去重后的归属计数；构筑可出现在多个来源，来源构筑数不能直接相加代替全局去重数。`original_completed_seed_slots` 统计这些组合已有的原四种子有效结果；`extra_seed_slots = eligible_pairs × 20 = jobs_to_add + existing_extra_seeds`。

断点续跑时，`eligible_pairs` 保持完整范围；`pairs_to_extend` 只计仍需写入缺失种子的组合，两者不应混用。各队列的 `expected_output_jobs` 为已有输出任务加本轮待追加任务。接续校验使用本轮实际报告，不再把某次预览的场数写死在代码里。任何统计修订都不会自行重启采集。

## 部署和预览

先把分支中的采集改动及本目录同步至 `/data1` 执行副本，保留该副本自己的 runtime 配置和数据。应同步的文件为：

```text
damage_model/catalog.py
damage_model/run_import.py
damage_model/mutations.py
damage_model/target_scope.py
configs/real-runs-8s.json
configs/mutations-targeted-8s.json
tools/one_off/backfill_targeted_seeds.py
```

以下命令默认仅做只读预览，不创建补采库或启动游戏。扫描原库全量任务并验证来源，需要一定 I/O 时间，标准错误会输出进度。

```bash
cd /data1/pl/ImageTask/wxq/Projects/Sts2Bot
.venv/bin/python -u -m tools.one_off.backfill_targeted_seeds \
  --sources data/collection-real-runs-v4.sqlite \
            data/collection-mutations-v2.sqlite \
            data/collection-targeted-mutations-v1.sqlite \
  --output-dir data/targeted-seed-backfill \
  --report /tmp/targeted-seed-backfill-preview.json
```

若使用另一批历史库，按最新版本在前的顺序显式补充 `--sources`；缺文件会直接报错，不会默默略过。只有确认新版库完整保留旧版输入索引和构筑/血缘时，才可省略旧库。

## 生成队列与执行

执行 `--apply` 时，先按原有流程暂停来源导入/变异生成并排空原库正在运行的战斗，使扫描期间的输入集合稳定；也可使用一致性备份。工具拒绝带 running 任务的来源库。然后在上面的命令末尾加 `--apply`，生成三个补采队列。该步骤仍不会启动游戏。输出目录的 manifest 固定本次输入和种子规则，目录锁防止两个准备进程同时写入。

补采使用原有 worker 池，仅消费有限队列，**不要用 `collect_continuous`**，否则会导入新来源/生成新变异。下面使用现有三个 runtime 演示，可按空闲独立 runtime 数量调整：

```bash
.venv/bin/python -u -m tools.collect_parallel \
  --db data/targeted-seed-backfill/collection-real-runs-v4.backfill.sqlite \
  --fallback-db data/targeted-seed-backfill/collection-mutations-v2.backfill.sqlite \
  --targeted-db data/targeted-seed-backfill/collection-targeted-mutations-v1.backfill.sqlite \
  --config configs/real-runs-8s.json \
  --runtimes configs/runtime-worker-01.json configs/runtime-worker-02.json configs/runtime-worker-03.json \
  --reserve-gib 0 --worker-start-gib 2 --continuous-workers
```

若新数据采集同时运行，必须分配不同的 runtime/Wine prefix 和 data_dir。现有 worker 锁继续生效。补采的新增结果只写入上述新库；备份这三个新库，并在后续训练 sources 中同时加入原始五批数据和补采库，真实补采的 kind 为 `real`，其余为 `mutation`。保留当前训练按来源和变异血缘划分组件的规则。旧快照查看器仍可能显示固定 4 个种子的文案；本次以数据库状态和补采报告为准。

## 独立数量复核（2026-09-19）

详见 [原库逐条核对报告](count-audit-20260919.json)。只读扫描三个来源的 `jobs` 和 `prior_collected_inputs`，按构筑 ID、编组 ID、种子去重，仅将原种子 0–3 至少一个完成、且章节与编组都命中名单的组合纳入补采。

| 来源 | 已完成过战斗的唯一构筑 | 命中补采条件的唯一构筑 | 补采组合 |
| --- | ---: | ---: | ---: |
| real-v4/v3 | 105,973 | 76,452 | 126,016 |
| mut-v2/v1 | 33,236 | 29,535 | 57,585 |
| targeted-v1 | 19,778 | 19,778 | 19,778 |
| 全局去重合计 | 158,987 | 125,765 | 203,379 |

全部已存储构筑为 163,309（包含尚无完成战斗的构筑）；历史唯一完成输入为 1,465,102 场。命中补采条件的构筑中，分别有 68,949 / 39,013 / 14,996 / 2,626 / 174 / 7 个构筑对应 1 / 2 / 3 / 4 / 5 / 6 个编组，加权合计 203,379 个组合。跨来源重复补采组合为 0。这些组合已有 813,153 个有效原四种子结果；追加 20 个种子的计划仍为 4,067,580 场。构筑数与组合数不同不构成重复采集，未因本次数量质疑更改目标名单或缩减范围。

正常采集新增了构筑级准入去重：重复构筑不通过新来源导入扩充编组或种子任务。历史补采仍按本工具的历史组合执行，逻辑互不调用。用户另开 4 个 worker 运行正常持续采集时，备份工具可用多个 `--additional-db` 将三个正常活动库加入同一串行备份轮次，避免并发全库复制。

2026-09-19 启动尝试已按用户要求取消：新增 4 个正常采集 worker 未进入战斗，相关控制器和预读任务已停止；正常采集禁止自动恢复，需用户再次明确要求。原有 25 个历史补采 worker 继续运行。构筑级去重和 24/4 种子配置保留。
