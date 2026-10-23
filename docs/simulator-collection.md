# 模拟器采集

`tools.collect_simulator` 使用独立 .NET 模拟器执行整场战斗。游戏规则和教师由冻结发布包提供；本仓库负责真实构筑导入、三队列调度、重试、结果校验和导出。仍采用 Silent A10、70/70、无药水、Medium short-only 8 秒、DOP 1、120 秒整场期限和原有 24/4 种子规则。

## 启动

```bash
# 默认单 worker，采集一场；重复运行接续已有任务
.venv/bin/python -m tools.collect_simulator

# 使用独立目录持续采集，只收集数据
.venv/bin/python -m tools.collect_simulator \
  --directory .local/simulator-continuous --continuous --workers 4

# 从本地 .run 文件导入，单轮每个 worker 最多采集 8 场
.venv/bin/python -m tools.collect_simulator \
  --directory .local/simulator-offline --import-runs /path/to/runs --limit 8
```

默认从公共来源同步一页。`--import-runs` 使用本地来源。真实、普通变异、专项变异仍按 2:1:1 领取，空队列借用容量。每轮完成后按原策略补充变异队列。持续采集通过 Ctrl+C、SIGTERM 或实例中 `db/real.continuous.stop` 请求停止。

VS Code 的“Sts2Bot: 模拟器采集（单任务沙箱）”使用 `.local/debug-simulator/`，保留数据供续跑与检查。

## 发布包与实例

[默认配置](../configs/simulator.json) 指向本机已冻结的模拟器发布目录。可通过 `--bundle /path/to/release` 或环境变量 `STS2_SIMULATOR_BUNDLE` 替换。发布目录须包含 `release.json`、教师、宿主 DLL 及运行配置、进度快照、目录和采集策略，另需其 `runtime-template.json` 指定的游戏资源与 .NET 可执行文件。

启动前逐文件核对发布清单，另核对游戏、求解器、RitsuLib、宿主、进度快照摘要及 JIT 设置。每个 worker 使用独立数据、临时文件和日志目录，无需准备 Wine prefix。更换发布包或 worker 数量时使用新的实例目录，避免将不同教师的结果写进同一批次。

实例中的 `active-collection.json` 记录三个数据库，`simulator-session.json` 固定发布清单摘要与并发数，`runtime-*.json` 记录各 worker 的运行参数。异常或超时按原策略最多尝试三次后隔离，保留日志和全部尝试；待提交结果先写入持久凭据，可在重启时恢复，避免因数据库写锁丢失已完成战斗。

整场请求超时后，采集器先终止所属进程组；必要时发送 SIGKILL，并最多等待 60 秒回收进程。Linux 内核 I/O 可能延迟信号生效，因此回收阶段独立于 120 秒战斗期限。回收成功后仍记录为 `StandaloneTimeout`；超过回收期限则保留进程所有权并报错，不能带着未退出的旧 host 启动下一场。

## 结果与训练

模拟器完成状态为 `StandaloneCompleted`，校验实际起始构筑和终局 HP 后写入 `complete` 任务。原生 `Passed` 与模拟器结果分别核对教师身份。保留发布包的 `isolated-experiment`、`productionReady=false`、`productionLabels=false` 等来源标记；代码接入和单场验证不改变这些标记，也不代表已经部署正式生产进程。

`tools.export_snapshot` 和 `train.snapshot` 均支持模拟器结果，导出时重新核对后端及摘要。训练默认拒绝混合不同后端、宿主或进度快照的教师。采集入口始终使用 `collect_only=True`。

通用控制器也支持显式指定模拟器教师与目录：

```bash
.venv/bin/python -m tools.collect_continuous \
  --db <instance>/db/real.sqlite \
  --mutation-db <instance>/db/mutations.sqlite \
  --targeted-db <instance>/db/targeted.sqlite \
  --config <bundle>/configs/real-runs-8s.json \
  --catalog <bundle>/catalogs/game-0.111.0.raw.json \
  --teacher <bundle>/teacher.json \
  --mutation-policy <bundle>/configs/mutations-8s.json \
  --targeted-policy <bundle>/configs/mutations-targeted-8s.json \
  --active-pointer <instance>/active-collection.json \
  --source-dir <instance>/source/live --backfill-dir <instance>/source/backfill \
  --runtimes <instance>/runtime-01.json --collect-only
```
