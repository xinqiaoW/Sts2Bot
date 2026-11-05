# 训练 / 推理 / 验证

构筑单次/加权遭遇评分入口见 [SCORE.md](SCORE.md)，战后奖励与卡牌 rollout 搜索见 [REWARD_POLICY.md](REWARD_POLICY.md)。

目标：`F(标准化卡组及逐张升级、附魔、持久状态, 遗物及采样计数, 原版怪物编组) → 标准化预期净掉血`，标签为 `净掉血 / 初始最大生命`（当前全部 70/70，即 `netHpLoss / 70`），另带死亡概率辅助头及可选的 9 维战斗过程辅助监督头。

数据只读取 8 秒教师的有效标签。默认 [configs/sources.json](configs/sources.json) 包含历史原生真实 v4/v3、普通变异 v2/v1 四个来源，**未包含模拟器、专项变异和历史种子补采库**。快照导出器只读访问源库，模型训练只读取导出的冻结快照，不写回采集输入或标签。

## 运行位置与准备条件

训练在准备好依赖、目录和数据的工作副本运行，模拟器数据位于各实例的 `db/`。来源数据库路径由训练配置明确列出，不从采集 session 自动发现。`prior_collected_inputs` 仅用于旧输入去重，不会被训练快照导出器当作完整标签导出。

训练环境使用 `python -m venv --system-site-packages`，在包含 PyTorch 的基础环境中安装 `lightgbm`、`rtdl_revisiting_models`、`tabm`、`pyarrow` 等训练依赖。Torch 模型可选 GPU，LightGBM 的训练实现使用 CPU。

可将既有已核验快照的 `sources/` 缓存准备到健康路径，用 `--reuse` 复用 `frozen: true` 来源；每个来源需齐备 `.battles.parquet`、`.builds.json.gz`、`.edges.json.gz`、`.meta.json`。`--only` 仅导出指定来源缓存，跳过合并，不能将其输出当成完整训练快照。

## 纳入模拟器、专项与补采数据

复制默认配置并替换或扩展 `sources`，保留 `teacher_compatibility_keys` 与 `split_buckets`：

- **模拟器来源**：列出同一实例的 `db/real.sqlite`（`kind: real`）、`db/mutations.sqlite` 与 `db/targeted.sqlite`（均为 `kind: mutation`）。快照导出支持 `StandaloneCompleted` 并核对 `execution_backend`、`validation_scope`、`standalone_host_sha256`、`standalone_unlock_state`、`progress_snapshot_sha256`；默认拒绝混合不同后端或不同宿主/解锁快照，跨后端合并须显式开启 `--allow-backend-mixture`。
- **历史原生专项与补采**：显式加入 `collection-targeted-mutations-v1.sqlite`（`mutation`）及补采输出目录中的 `*.backfill.sqlite`（真实为 `real`，其余为 `mutation`）。仍在写入的库设为 `frozen: false`。

## 流程

### 全量 8 秒语料训练

[sources-full-8s.json](configs/sources-full-8s.json) 列出原生历史五库、三份种子补采库、模拟器旧三库与续采三库共十四个来源（本机部署清单，其他机器须先替换数据库路径）。去重按 `sources` 顺序优先保留靠前来源，所有有效来源共同参与全局源局/血缘连通组划分。

- 复用冻结缓存前可用 `python -m train.verify_cache --snapshot <旧快照> --cache <sources目录> --output <输出.json>` 核验 SHA-256、标签、教师、构筑状态及连通组。
- `train.stream_export` 使用只读事务和主表 rowid 扫描分批写入 Parquet；不同磁盘上的来源可用独立的 `train.stream_export --only ...` 并行准备。
- 全量跨后端实验显式使用 `--allow-backend-mixture`，在强制相同游戏版本、求解器、8000 ms 搜索等核心设置的前提下合并原生与模拟器来源：

```bash
PYTHONPATH="$PWD" OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=2 \
    .venv-train/bin/python -P -m tools.train_full_corpus \
    --config train/configs/sources-full-8s.json \
    --directory /absolute/path/to/full-corpus --gpus 0,1
```

该流程依次导出尚缺来源、合并去重并划分、预生成特征，再训练模型并生成比较与测试样例报告（`--prepare-only` 在特征准备后结束）。运行目录中的 `pipeline-state.json`、`logs/`、`snapshot/`、`checkpoints/`、`report/` 分别保存状态、日志、冻结数据、模型和评估。

### 分步快照导出、训练与推理

```bash
# 1. 导出一致快照（封存库可通过 --reuse 复用上一次快照导出）
.venv-train/bin/python -m train.snapshot --config /absolute/path/to/sources.json \
    --reuse /absolute/path/to/previous-snapshot
# → data/train-snapshots/<UTC 时间戳>/{battles.parquet, builds.json.gz, targets.json, manifest.json, sources/}

snapshot_dir=/absolute/path/to/exported-snapshot
checkpoint_dir=/absolute/path/to/model-comparison

# 2. （可选）从源库战斗 trace 提取可断点续跑的 9 维过程辅助标签 Parquet
.venv-train/bin/python -m train.aux_labels build --snapshot "$snapshot_dir" --workers 8

# 3. 训练单个模型（可通过 --set role_priors=true --set aux_supervision=true 启用先验与过程监督）
.venv-train/bin/python -m train.train --snapshot "$snapshot_dir" --model set_transformer --device cuda:0

# 4. 多模型比较（torch 模型按 GPU 轮转，LightGBM 在 CPU 并行）
.venv-train/bin/python -m train.compare --snapshot "$snapshot_dir" --gpus 0,1 --output "$checkpoint_dir"

# 5. 推理（单个或多个 checkpoint 均值集成）
.venv-train/bin/python -m train.predict --checkpoint "$checkpoint_dir/tabm" \
    --build build.json --target BOWLBUGS_WEAK --max-hp 70
.venv-train/bin/python -m train.predict --checkpoint "$checkpoint_dir/tabm" \
    --checkpoint "$checkpoint_dir/lightgbm" --builds-jsonl inputs.jsonl

# 6. 用更新的快照验证旧 checkpoint（自动排除训练/验证过的构筑及其连通组）
.venv-train/bin/python -m train.evaluate --snapshot /absolute/path/to/newer-snapshot \
    --checkpoint "$checkpoint_dir/tabm"

# 7. 具体样例与误差分析（读各模型的 predictions.parquet，默认 --split test）
.venv-train/bin/python -m train.inspect --snapshot "$snapshot_dir" \
    --checkpoints "$checkpoint_dir" --primary set_transformer

# 测试
.venv-train/bin/python -m pytest tests/test_train_pipeline.py tests/test_aux_labels.py -q
```

## 快照与划分

- 每条记录必须是数据库 `status='complete'`，且 `combatEnded`、观察 `complete` 均为真；Wine 结果为 `Passed`，模拟器结果为 `StandaloneCompleted` 并通过后端身份校验。导出重新运行 `validate_hp` 与逐张 `validate_cards`，任何不一致均报错。
- 同一 `(build, target, seed)` 出现在多个库时只保留 `sources` 顺序靠前者，去重数量写入 `manifest.json`。
- 教师兼容性：各库在 `teacher_compatibility_keys`（求解器、游戏 SHA、8000 ms、Medium、DOP 1 等）和后端身份键上须一致。
- 划分按连通组：`build_origins`（构筑—源局）、`mutation_target_origins`（变异子—父源局）、`mutation_lineage`（子—父）做并查集，一个连通组只进一个集合（80/10/10，按组内源局哈希分桶）。任何集合为空即拒绝训练。

## 特征与先验

- **稀疏视图**（`train/features.py`）：与 `damage_model.encoding.Encoder.encode` 一致的键与缩放，只保留训练集中出现过的键；合法但未见过的键在推理时以 `untrained_features` 报告，非法键直接拒绝。供 `repo_mlp`、`rtdl_*`、`tabm`、`lightgbm` 使用。
- **token 视图**（`train/features.py`）：每张牌一个 token（牌 ID、升级、附魔 ID、持久状态符号 + 附魔数值），每件遗物一个 token（遗物 ID、计数符号 + 顺序），目标与全局各一个 token。供 `set_transformer` 使用。
- **领域角色先验与牌组上下文**（`train/role_priors.py`）：`set_transformer` 开启 `role_priors=True` 时，为每个卡牌/遗物 token 注入 16 维确定性角色向量（费用、类别、终端/过牌/能量/成长/减伤权重，以及小刀/毒/弃牌的源与收益权重）与 8 维牌组动态供需交互上下文，经两层 MLP 融入 `TokenEmbedding`。

## 模型与监督信号

| 名称 | 来源 | 适配 |
|---|---|---|
| `repo_mlp` | 仓库 `damage_model.model.DamageNet` | 同结构，接入统一训练循环 |
| `rtdl_mlp` / `rtdl_resnet` | `rtdl_revisiting_models`（Gorishniy 等，NeurIPS 2021） | `d_in` = 词表大小，`d_out=2` |
| `tabm` | `tabm`（Gorishniy 等，ICLR 2025） | k=32 成员各自计算损失，预测取均值 |
| `set_transformer` | 官方 Set Transformer `modules.py`（Lee 等，ICML 2019） | 加 key padding mask；可选 `role_priors` 与 9 维 `aux_head` |
| `lightgbm` | LightGBM | 回归 + 死亡二分类两棵 booster，直接吃 CSR |

超参数见 [configs/models.json](configs/models.json)，可用 `--set key=value` 覆盖。Torch 主损失为 `MSE(标准化掉血) + 0.1·BCE(死亡)`，同一输入的重复种子按 `1/种子数` 加权，早停看验证集 `pair_mae_hp`。

启用 `aux_supervision=True`（权重 `aux_loss_weight`，默认 `0.05`）时，`train/aux_labels.py` 从战斗记录提取 9 维过程指标（`turns_norm` + 每回合伤害、伤害稳定性、每回合格挡、非斩杀回合格挡稳定性、有效产费、有效用费、额外过牌、每回合出牌数），按训练集有效样本 Z-score 标准化并带掩码计算 Smooth L1 辅助损失（无详细 trace 的历史原生样本仅监督 `turns_norm`）。

可通过 `gpu_memory_limit_gib` 限制当前 Torch 进程的显存分配，并用 `prediction_batch_size` 控制验证及最终预测的批量大小（默认 4096）。

## 指标与产物

- `row_*`：逐场对战误差（含战斗种子波动），单位 HP。
- `pair_*`：先对同一 `(构筑, 目标)` 的所有种子取均值再比较，是评估预期掉血的主要指标；`pair_r2` 为对 pair 均值的解释比例。
- 组内波动参考：`within_pair_rmse_hp` 是有限种子样本的组内标准差，`loo_seed_mean_mae_hp` 用同输入其他种子均值预测单场（报告 JSON 中沿用字段名 `test_noise_floor`，仅代表有限种子样本内波动）。
- 死亡头：Brier 与 AUC。全部指标另按来源类型（real/mutation）、幕、来源库分组。

不同快照的测试连通组与分布不同，模型优化效果应在同一固定留出集上比较。

模型产物保存在 `checkpoints/train/<stamp>/<model>/`：`artifact.json`、`vocab.json`、`weights.pt`（或 `*.lgb.txt`）、`metrics.json`、`history.json`、`predictions.parquet`、`training-builds.json`。推理只依赖该目录与 `catalogs/`，输出 `normalized_expected_hp_loss`（`[0,1]`）、`expected_hp_loss`（`× max_hp`）、`death_probability`、`untrained_features`；目标无训练覆盖时拒绝，`--strict` 时任何未训练特征也拒绝。
