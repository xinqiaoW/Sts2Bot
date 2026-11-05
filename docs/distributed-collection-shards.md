# 分布式模拟器分片采集指南

本文档说明如何通过 `tools.create_shards` 与 `tools.run_shard` 将历史原生对战语料拆分为多个独立 SQLite 分片，在多台 Linux 节点上并行重跑独立模拟器采集，以补齐完整战斗逐回合 `trace`（供 `train.aux_labels` 提取 9 维过程辅助监督信号）。

## 一、生成分片与产物概览

在主节点使用 `tools.create_shards` 从训练快照切分出 3 个自包含 SQLite 分片：

```bash
.venv-train/bin/python -m tools.create_shards \
  --snapshot /data/pl/Sts2Bot-training-20261031/snapshot \
  --bundle /data1/pl/ImageTask/wxq/Projects/standalone-rollout-readiness-20260929/candidate-release-v5 \
  --out-dir /data1/pl/ImageTask/wxq/Projects/Sts2Bot_dist_collection/shards
```

| 分片文件 | 总战斗场数 | 独立构筑数 | 推荐并发 (Workers) | 预计耗时 (5~7s/场) |
|---|---:|---:|:---:|:---:|
| `shards/shard_1.sqlite` | 469,395 | 48,253 | 6 ~ 8 | 约 3.5 ~ 4.5 天 |
| `shards/shard_2.sqlite` | 469,395 | 48,246 | 8 ~ 16 | 约 2 ~ 3.5 天 |
| `shards/shard_3.sqlite` | 469,393 | 48,151 | 16 ~ 24 | 约 1.5 ~ 2.5 天 |

- **总计**：1,408,183 场战斗，覆盖 144,650 个独立构筑，按血缘连通分量（Connected Components）划分，分片之间构筑零交叉。
- **幕次分布**：每个分片均均衡包含约 14w 场 `HIVE`（巢穴）与约 12w 场 `GLORY`（荣耀）。

## 二、运行节点环境要求

- **操作系统**：Linux（需要 POSIX 进程组隔离）
- **CPU / 内存**：8 核以上最佳，内存推荐 $\ge 16\text{ GB}$
- **磁盘空间**：
  - 采集前：自包含基础包约 2.3 GB + 单个分片 SQLite 约 2.8 GB $\approx 5.1\text{ GB}$
  - 采集完成时：记录完整战斗 `trace` 后，单分片数据库增至约 $18\sim 22\text{ GB}$
  - 建议节点保留 $\ge 40\text{ GB}$ 空闲磁盘空间
- **Python 环境**：Python 3.10+ 或 3.11+

## 三、部署与启动流程

### 步骤 1：同步采集工具包与对应分片

主节点自包含完整包目录（含模拟器发布包、游戏资源与 .NET 运行时）：
`/data1/pl/ImageTask/wxq/Projects/Sts2Bot_dist_collection/package/`

在目标节点上同步运行包与分配给该节点的分片数据库（以 `shard_1.sqlite` 为例）：

```bash
mkdir -p ~/sts2_worker && cd ~/sts2_worker
rsync -avzP user@<主节点IP>:/data1/pl/ImageTask/wxq/Projects/Sts2Bot_dist_collection/package/ .
rsync -avzP user@<主节点IP>:/data1/pl/ImageTask/wxq/Projects/Sts2Bot_dist_collection/shards/shard_1.sqlite .
```

### 步骤 2：安装基础 Python 依赖

```bash
cd ~/sts2_worker
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 步骤 3：启动采集

使用仓库入口 `python -m tools.run_shard` 或自包含包内的封装脚本 `./run_shard.sh <分片数据库路径> [并发Worker数]`：

```bash
# 方式 A：使用自包含包脚本后台运行
nohup ./run_shard.sh shard_1.sqlite 8 > run.log 2>&1 &

# 方式 B：直接调用 Python 模块
nohup .venv/bin/python -m tools.run_shard --db shard_1.sqlite --workers 8 --bundle ./bundle > run.log 2>&1 &

# 查看实时采集进度
tail -f run.log
```

日志每 15 秒输出一次进度摘要（完成数、待处理数、失败数、速率与预计剩余时间）。

## 四、暂停、恢复与回传合并

1. **暂停 / 优雅停止**：发送 `kill -SIGTERM <PID>` 或在交互终端按 `Ctrl+C`。`tools.run_shard` 会在各 worker 目录写入 `collector.stop`，等待在途战斗完成提交并释放 SQLite 锁后退出。
2. **断点续跑**：重新执行相同启动命令即可，工具会自动跳过 `complete` 条目并继续消费剩余 `pending` 任务。
3. **回传与提取辅助标签**：当日志显示 `All pending jobs finished!` 时，将完成的 `shard_X.sqlite` 回传至主节点并纳入训练来源配置，导出快照后运行 `python -m train.aux_labels build --snapshot <快照目录>` 提取 9 维过程辅助监督标签。
