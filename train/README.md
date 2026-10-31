# 训练 / 推理 / 验证

目标：`F(标准化卡组及逐张升级、附魔、持久状态, 遗物及采样计数, 原版怪物编组) → 标准化预期净掉血`，标签为 `净掉血 / 初始最大生命`（当前全部 70/70，即 `netHpLoss / 70`），另带死亡概率辅助头。

数据只读取 8 秒教师的有效标签。默认 [configs/sources.json](configs/sources.json) 包含历史原生真实 v4/v3、普通变异 v2/v1 四个来源，**未包含模拟器、专项变异和历史种子补采库**；它不是全部采集数据的来源清单。快照导出器只读访问源库，模型训练只读取导出的冻结快照，不写回采集输入或标签。

## 运行位置与准备条件

训练在准备好依赖、目录和数据的工作副本运行，模拟器数据位于各实例的 `db/`。来源数据库路径由训练配置明确列出，不从采集 session 自动发现。训练使用独立环境及完整冻结来源，不与持续采集控制器绑定。

运行前检查训练解释器、依赖、GPU 和各来源文件，尤其是虚拟环境的实际解释器路径，以及封存 real-v3 / mut-v1 的完整标签或已验证导出缓存。`prior_collected_inputs` 用于旧输入去重，不会被训练快照导出器当作完整标签导出；新版库不能单独替代旧库的训练数据。

训练环境使用 `python -m venv --system-site-packages`，在包含 PyTorch 的基础环境中安装 `lightgbm`、`rtdl_revisiting_models`、`tabm`、`pyarrow` 等训练依赖。仓库尚无独立的训练依赖锁定文件，重建环境需核对实际包版本。不向采集环境安装训练依赖。Torch 模型可选 GPU，LightGBM 的训练实现使用 CPU；默认 `--gpus 0,1` 是工具参数，不代表这些 GPU 当前空闲。

默认 [configs/sources.json](configs/sources.json) 按 real-v4、real-v3、mut-v2、mut-v1 顺序去重。可将既有已核验快照的 `sources/` 缓存准备到健康路径，用 `--reuse` 复用 frozen 来源；每个来源需齐备 `.battles.parquet`、`.builds.json.gz`、`.edges.json.gz`、`.meta.json`。缺少缓存时工具会尝试读取配置中的数据库，不能靠 `--reuse` 绕过缺失数据。

若明确只训练活动来源，另建显式 `--config`，保留教师兼容键与划分设置，并在报告中注明覆盖变化。`--only` 仅导出指定来源缓存，跳过合并，不能把其输出当成完整训练快照。不要通过跳过卡牌验证或忽略教师不匹配来凑齐数据。

## 模拟器训练来源

复制默认配置并替换 `sources`，保留 `teacher_compatibility_keys` 与 `split_buckets`。以唯一 `name` 列出同一实例的 `db/real.sqlite`（`kind: real`）、`db/mutations.sqlite` 与 `db/targeted.sqlite`（均为 `kind: mutation`），把 `db` 填为实际路径，再通过 `--config` 指定。仍在写入的库设 `frozen: false`。

快照导出支持 `StandaloneCompleted`，并保留实验后端与来源身份；这不改变发布包的生产验证标记。合并除配置中的教师兼容键外，还固定核对 `execution_backend`、`validation_scope`、`standalone_host_sha256`、`standalone_unlock_state`、`progress_snapshot_sha256`，默认拒绝把模拟器与旧 Wine 标签或不同宿主/解锁快照混在一起。

## 纳入历史原生专项与补采数据

复制来源配置后，通过 `--config` 指定扩展配置，保留 `teacher_compatibility_keys` 与 `split_buckets`。除了原四个来源，应显式加入需要训练的专项库及补采库：

| 新增来源 | `kind` | 数据库位置 |
| --- | --- | --- |
| 专项变异 v1 | `mutation` | `data/collection-targeted-mutations-v1.sqlite` |
| 真实补采 | `real` | 补采输出目录中的 `collection-real-runs-v4.backfill.sqlite` |
| 普通变异补采 | `mutation` | 补采输出目录中的 `collection-mutations-v2.backfill.sqlite` |
| 专项变异补采 | `mutation` | 补采输出目录中的 `collection-targeted-mutations-v1.backfill.sqlite` |

每项须有唯一的 `name`、正确的 `db` 和 `frozen`。仍在写入的库设为 `frozen: false`；只有不再变化的来源才允许复用冻结缓存。[sources-data1.json](configs/sources-data1.json) 是绑定特定本机路径的旧部署配置，同样只有原四个来源，不能直接当作当前数据库清单。若只纳入部分来源，应在报告中明确范围。

旧结果与新增种子先按 `(build, target, seed)` 去重，再按共享构筑、源局和变异血缘统一划分。无需所有组合都凑满 24 个有效结果才导出，但应记录每个组合的实际有效样本数。

## 流程

### 全量 8 秒语料训练

[sources-full-8s.json](configs/sources-full-8s.json) 列出原生历史五库、三份种子补采库、模拟器旧三库与当前续采三库，共十四个来源。它是本机部署清单，其他机器须先替换数据库路径。2 秒旧数据不在此配置中。去重优先保留当前模拟器结果，其次为旧模拟器、原生与补采结果；所有有效来源都参与全局源局/血缘分组。

原生冻结导出可以复用，但应先用 `train.verify_cache` 对照原快照的 SHA-256、逐条标签、教师、构筑状态及源局连通组核验缓存：

```bash
.venv-train/bin/python -m train.verify_cache \
    --snapshot /absolute/path/to/previous-snapshot \
    --cache /absolute/path/to/full-corpus/snapshot/sources \
    --output /absolute/path/to/full-corpus/verified-native-cache.json
```

`train.stream_export` 使用只读事务和主表 rowid 扫描，避免依赖旧库的损坏状态索引，并分批写入 Parquet。默认遇到错误立即停止；仅配置了 `recover_invalid_rows` 的旧故障批次允许二分定位损坏行、逐条记录拒绝原因，再导出通过相同 HP、起始牌组及后端身份验证的结果。锁等待、临时 I/O 错误不作为坏行丢弃。源局和血缘元数据读取失败仍会中止，避免因遗漏关系产生测试泄漏。恢复模式缺失的历史完成时间保留为 NULL 并计数，不伪造时间，也不影响 HP 监督标签。

全量实验显式使用 `--allow-backend-mixture`：允许合并原生和模拟器来源，同时仍强制相同游戏、求解器、8000 ms 搜索及其他核心设置。此开关不同于忽略所有教师差异；默认的严格兼容检查仍保留。快照及模型保留实验来源标记，报告分别列出后端误差；混合训练不代表模拟器已经通过生产等价验证。

准备好训练环境和已核验的冻结缓存后运行：

```bash
# 使用包含 WAL 修复的私有 SQLite 模块；此目录应包含 _sqlite3 扩展。
sqlite_module_dir=/absolute/path/to/private-sqlite-module
PYTHONPATH="$PWD:$sqlite_module_dir" OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    .venv-train/bin/python -P -m tools.train_full_corpus \
    --config train/configs/sources-full-8s.json \
    --directory /absolute/path/to/full-corpus --gpus 6,7
```

该流程依次导出尚缺的来源、合并去重并划分、预生成特征，再训练 MLP、TabM 与 LightGBM，最后生成比较和测试样例。实际使用指定列表中显存占用低于 512 MiB、利用率低于 5% 的 GPU；没有空闲卡时等待。LightGBM 使用 8 个 CPU 线程。`--prepare-only` 在特征准备后结束。

运行目录中的 `pipeline-state.json`、`logs/`（各模型在 `logs/models/`）、`snapshot/`、`checkpoints/`、`report/` 分别保存阶段状态、日志、冻结数据、模型和评估。状态中的 PID 须结合实际进程身份判断；失败来源不会被静默跳过。重复运行复用已完成的来源缓存，重新取得活动库快照时应选择新的输出目录。最终数据量以快照中的有效行数及去重清单为准，不用历史心跳总量代替训练样本数。

不同磁盘上的来源可用独立的 `train.stream_export --only ...` 进程同时准备。命令按来源名称取得缓存写锁，等待另一个同名导出完成后复用已发布缓存；完成清单通过原子替换发布。`--force` 显式重新导出已完成的缓存。特征准备使用迭代器逐对构造输入，避免同时保留几十万个展开后的构筑对象。

在已准备好依赖与目录的仓库根目录执行。将以下来源配置、快照和 checkpoint 路径替换为实际位置；没有可复用缓存时省略 `--reuse`，并确保所有来源库可读取。

```bash
# 1. 导出一致快照（每库一次只读事务；封存库可复用上一次快照的导出）
.venv-train/bin/python -m train.snapshot --config /absolute/path/to/sources.json \
    --reuse /absolute/path/to/previous-snapshot
# → data/train-snapshots/<UTC 时间戳>/{battles.parquet, builds.json.gz, targets.json, manifest.json, sources/}

# 填入导出所得快照和本次模型输出目录
snapshot_dir=/absolute/path/to/exported-snapshot
checkpoint_dir=/absolute/path/to/model-comparison

# 2. 训练单个模型
.venv-train/bin/python -m train.train --snapshot "$snapshot_dir" --model tabm --device cuda:0

# 3. 多模型比较（torch 模型按 GPU 轮转，LightGBM 在 CPU 并行）
.venv-train/bin/python -m train.compare --snapshot "$snapshot_dir" --gpus 0,1 --output "$checkpoint_dir"
# → $checkpoint_dir/<model>/，train/reports/<快照名>/comparison.{md,json}

# 4. 推理（单个或多个 checkpoint 均值集成）
.venv-train/bin/python -m train.predict --checkpoint "$checkpoint_dir/tabm" \
    --build build.json --target BOWLBUGS_WEAK --max-hp 70
.venv-train/bin/python -m train.predict --checkpoint "$checkpoint_dir/tabm" \
    --checkpoint "$checkpoint_dir/lightgbm" --builds-jsonl inputs.jsonl

# 5. 用更新的快照验证旧 checkpoint（自动排除训练/验证过的构筑及其连通组）
.venv-train/bin/python -m train.evaluate --snapshot /absolute/path/to/newer-snapshot \
    --checkpoint "$checkpoint_dir/tabm"

# 6. 具体样例与误差分析（读各模型的 predictions.parquet，不重新推理）
.venv-train/bin/python -m train.inspect --snapshot "$snapshot_dir" \
    --checkpoints "$checkpoint_dir" --primary set_transformer
# → train/reports/<stamp>/examples-test.md（校准表、编组内区分能力 vs “编组均值”基线、按编组/幕/牌数误差、最差高估/低估、模型分歧、随机样例）
#   默认 --split test：样例全部来自留出的测试连通组，训练/验证集里没有这些构筑及其变异亲属

# 测试
.venv-train/bin/python -m pytest tests/test_train_pipeline.py -q
```

## 快照与划分

快照逐库取得一致的只读视图；多个来源库并非同一原子时间点，分别记录导出时间。模型训练仅读取冻结结果。`train.evaluate` 默认排除 checkpoint 已见构筑及连通组；`--all-rows` 不再是独立留出评估，须另行标记。

- 每条记录必须是数据库 `status='complete'`，且 `combatEnded`、观察 `complete` 均为真；Wine 结果为 `Passed`，模拟器结果为 `StandaloneCompleted` 并通过后端身份校验。导出重新运行 `validate_hp` 与逐张 `validate_cards`，任何不一致都报错。
- 同一 `(build, target, seed)` 出现在多个库时只保留 `sources.json` 顺序靠前者（v4 优先于 v3），去重数量写入 `manifest.json`。
- 教师兼容性：各库在 `teacher_compatibility_keys`（求解器、游戏 SHA、8000 ms、Medium、DOP 1 等）和上述后端身份键上须一致。历史 Wine 协议 2/3 只按这份显式兼容配置组合；采集器摘要不同仍保留各自教师，不能仅凭搜索预算相同推定兼容。
- 划分按连通组：`build_origins`（构筑—源局）、`mutation_target_origins`（变异子—父源局）、`mutation_lineage`（子—父）做并查集，一个组只进一个集合（80/10/10，按组内源局哈希分桶，不保证场次数正好按该比例）。任何集合为空即拒绝训练。

## 特征

`train/features.py`：

- 稀疏视图：与 `damage_model.encoding.Encoder.encode` 完全一致的键与缩放（`tests/test_train_pipeline.py` 校验等价），只保留训练集中出现过的键；合法但未见过的键在推理时以 `untrained_features` 报告，非法键直接拒绝。供 `repo_mlp`、`rtdl_*`、`tabm`、`lightgbm` 使用。
- token 视图：每张牌一个 token（牌 ID、升级、附魔 ID、持久状态符号 + 附魔数值），每件遗物一个 token（遗物 ID、计数符号 + 顺序），目标与全局各一个 token。供 `set_transformer` 使用。

## 模型（均为现有实现的适配）

| 名称 | 来源 | 适配 |
|---|---|---|
| `repo_mlp` | 仓库 `damage_model.model.DamageNet` | 同结构，接入统一训练循环 |
| `rtdl_mlp` / `rtdl_resnet` | `rtdl_revisiting_models`（Gorishniy 等，NeurIPS 2021） | `d_in` = 词表大小，`d_out=2` |
| `tabm` | `tabm`（Gorishniy 等，ICLR 2025） | k=32 成员各自计算损失，预测取均值 |
| `set_transformer` | 官方 Set Transformer `modules.py`（Lee 等，ICML 2019） | 加 key padding mask 以批处理变长牌组 |
| `lightgbm` | LightGBM | 回归 + 死亡二分类两棵 booster，直接吃 CSR |

超参数见 [configs/models.json](configs/models.json)，可用 `--set key=value` 覆盖。损失 `MSE(标准化掉血) + 0.1·BCE(死亡)`，同一输入的重复种子按 `1/种子数` 加权（与仓库训练一致），早停看验证集 pair MAE。验证和最终预测对每个构筑、目标输入计算一次，再回填全部种子行；训练监督和评估统计覆盖所有有效战斗记录。

## 指标

- `row_*`：逐场对战误差（包含战斗种子带来的波动），单位 HP。
- `pair_*`：先对同一 (构筑, 目标) 的所有种子取均值再比较，是评估“预期掉血”的主要指标；`pair_r2` 为对 pair 均值的解释比例。
- 组内波动参考：`within_pair_rmse_hp` 是有限种子样本的组内波动，`loo_seed_mean_mae_hp` 用同输入其他种子均值预测单场。它们不是已知总体分布的不可约误差下限；有限种子均值本身也有采样误差。
- 死亡头：Brier 与 AUC。全部指标另按来源类型（real/mutation）、幕、来源库分组。

报告生成器目前仍使用历史名称“噪声下限”和 `test_noise_floor` 字段；其统计含义以上述解释为准。这些历史字段名不表示已经测得总体不可约误差。

## 固定快照报告

[reports/](reports/) 按快照保存模型比较、样例与实验，指标和数量只描述对应冻结数据。报告实际纳入的来源以其清单为准，不代表默认来源配置已更新。[损失函数与 pair 监督实验](reports/20260916-exp/experiments.md)的训练实现尚未接入标准入口。

不同快照的测试连通组与分布不同，不能直接用跨报告 MAE 升降判断模型进退；优化效果应在同一固定留出集上比较。保留报告中的指标、设置、耗时和快照身份用于复现。

## 产物

`checkpoints/train/<stamp>/<model>/`：`artifact.json`（模型、超参、代码分支与文件摘要、快照文件摘要、老师、覆盖目标、指标摘要）、`vocab.json`、`weights.pt` 或 `*.lgb.txt`、`metrics.json`、`history.json`、`predictions.parquet`、`training-builds.json`。推理只依赖该目录与 `catalogs/`。全量报告逐来源列出有效导出、无效完成结果、跨库重复及最终保留数量。

推理输出 `normalized_expected_hp_loss`（[0,1]）、`expected_hp_loss`（× max_hp）、`death_probability`、`untrained_features`；目标没有训练覆盖时拒绝，`--strict` 时任何未训练特征也拒绝。
