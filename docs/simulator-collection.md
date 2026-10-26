# 模拟器采集

`tools.collect_simulator` 使用独立 .NET 模拟器执行整场战斗。游戏规则和教师由冻结发布包提供；本仓库负责真实构筑导入、三队列调度、重试、结果校验和导出。采集采用 Silent A10、70/70、无药水、Medium short-only 8 秒、DOP 1、120 秒整场期限和 24/4 种子规则。

## 准备发布包

需要 Linux、Python 3.11+、可用的项目 Python 环境，以及单独准备的冻结模拟器发布包。Python 使用的 SQLite 须包含 [WAL-reset 修复](continuous-collection.md#故障停止与恢复)。发布包、游戏资源和 .NET 不随 Git checkout 提供。发布目录须包含 `release.json`、`teacher.json`、`runtime-template.json`、`host/`、`progress-snapshot.json`、`catalogs/` 下的目录数据及 `configs/` 下的三份采集策略；游戏资源和 .NET 路径由运行模板指定。

按以下优先级选择发布包：命令行 `--bundle`、环境变量 `STS2_SIMULATOR_BUNDLE`、仓库根目录的 `configs/simulator.json`。最后一项是被 Git 忽略的本机配置，需自行创建，内容为：

```json
{"bundle": "/absolute/path/to/release"}
```

也可不建配置文件，直接设置环境变量。VS Code 的沙箱入口不接受命令行参数，使用环境变量或这份本机配置。

## 启动

以下命令在仓库根目录执行：

```bash
export STS2_SIMULATOR_BUNDLE=/absolute/path/to/release

# 默认单 worker，采集一场；重复运行接续已有任务
.venv/bin/python -m tools.collect_simulator

# 使用独立目录持续采集，只收集数据
.venv/bin/python -m tools.collect_simulator \
  --directory .local/simulator-continuous --continuous --workers 4

# 从本地 .run 文件导入，单轮每个 worker 最多采集 8 场
.venv/bin/python -m tools.collect_simulator \
  --directory .local/simulator-offline --import-runs /path/to/runs --limit 8
```

单轮先尝试同步一页公共来源；处于限流等待时沿用已有队列。`--import-runs` 使用本地来源，只支持单轮模式，不能与 `--continuous` 同用。`--limit` 只限制单轮每个 worker 的采集场数。真实、普通变异、专项变异仍按 2:1:1 领取，空队列借用容量。每轮完成后按原策略补充变异队列。持续采集通过 Ctrl+C、SIGTERM 或实例中 `db/real.continuous.stop` 请求停止；停止、恢复和备份见[持续采集](continuous-collection.md)。

VS Code 的“Sts2Bot: 模拟器采集（单任务沙箱）”使用 `.local/debug-simulator/`，保留数据供续跑与检查。

## 发布包与实例

默认实例位于仓库根目录的 `.local/simulator-collect/`。`--directory` 的相对路径按启动命令的工作目录解析；使用绝对路径可将数据库、日志及来源放在独立数据盘。发布包只提供冻结输入，运行结果写入实例。

启动前逐文件核对发布清单，另核对游戏、求解器、RitsuLib、宿主、进度快照摘要及 JIT 设置。每个 worker 使用独立数据、临时文件和日志目录，无需准备 Wine prefix。更换发布包或 worker 数量时使用新的实例目录，避免将不同教师的结果写进同一批次。

实例中的 `active-collection.json` 记录三个数据库，`simulator-session.json` 固定发布清单摘要与并发数，`runtime-*.json` 记录各 worker 的运行参数。异常或超时按原策略最多尝试三次后隔离，保留日志和全部尝试；待提交结果先写入持久凭据，可在重启时恢复，避免因数据库写锁丢失已完成战斗。

整场请求超时后，采集器先向所属进程组发送 SIGTERM，等待 2 秒后必要时发送 SIGKILL。若内核尚未完成回收，保持进程所有权，每等待 60 秒记录一次事件，直到确认退出后才允许下一场。60 秒是等待日志的间隔，不是回收上限；战斗的 120 秒期限不变，结果仍记为 `StandaloneTimeout`。

## 结果与训练

模拟器完成状态为 `StandaloneCompleted`，校验实际起始构筑和终局 HP 后写入 `complete` 任务。原生 `Passed` 与模拟器结果分别核对教师身份。保留发布包的 `isolated-experiment`、`productionReady=false`、`productionLabels=false` 等来源标记；代码接入和单场验证不改变这些标记，也不代表已经部署正式生产进程。

`tools.export_snapshot` 和 `train.snapshot` 均支持模拟器结果，导出时重新核对后端及摘要。训练默认拒绝混合不同后端、宿主或进度快照的教师。采集入口始终使用 `collect_only=True`。

通用控制器也支持显式指定模拟器教师与目录，要求主库已存在且已初始化。日志和证据中的相对路径基于工作目录，因此须在实例目录运行，并显式提供部署代码与解释器。以下路径须替换为实际位置；首次创建实例优先使用上面的模拟器入口：

```bash
collection_dir=/absolute/path/to/instance
simulator_bundle=/absolute/path/to/release
collection_code=/absolute/path/to/deployed-code
collection_python=/absolute/path/to/project/.venv/bin/python
(
  cd "$collection_dir" || exit
  PYTHONPATH="$collection_code" "$collection_python" -P -m tools.collect_continuous \
    --db "$collection_dir/db/real.sqlite" \
    --mutation-db "$collection_dir/db/mutations.sqlite" \
    --targeted-db "$collection_dir/db/targeted.sqlite" \
    --config "$simulator_bundle/configs/real-runs-8s.json" \
    --catalog "$simulator_bundle/catalogs/game-0.111.0.raw.json" \
    --teacher "$simulator_bundle/teacher.json" \
    --mutation-policy "$simulator_bundle/configs/mutations-8s.json" \
    --targeted-policy "$simulator_bundle/configs/mutations-targeted-8s.json" \
    --active-pointer "$collection_dir/active-collection.json" \
    --source-dir "$collection_dir/source/live" --backfill-dir "$collection_dir/source/backfill" \
    --runtimes "$collection_dir/runtime-01.json" --collect-only
)
```
