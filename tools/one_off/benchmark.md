# 补采并发阶梯压测

本工具只用于一次性吞吐实验，不修改原生战斗或数据库锁重试逻辑。代码维护于 `/data2/pl/ImageTask/wxq/Projects/Sts2Bot`，执行副本和证据位于 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot/data/seed-benchmark-20260919`。

## 固定条件

- 原生游戏/采集器/教师摘要保持原值，Medium、short_only、8,000 ms、DOP 1、120 秒战斗超时。
- 25、40、60、80 个独立 runtime，分别拥有 Wine prefix、存档和协议目录；公共游戏文件继续共享。
- 原有 25 套 runtime 确认无 collector 锁持有后使用；55 套新增 prefix 从没有活动 Wine server 的 worker-10 模板复制。
- 真实和定向来源各 43 个编组，普通变异来源 30 个编组，每个来源–编组确定性选择 64 个已有完成采集的构筑，沿用其来源/血缘。
- 战斗种子使用原序列索引 4–23，各档复制同一份队列模板并按编组轮转。真实/普通变异/定向变异沿用现有 2:1:1 领取调度。
- 全部 worker 启动后预热 60 秒，随后计时 600 秒；测量不包括启动、预热和结束时的在途战斗排空。
- 保持原有备份服务运行，记录其物理/逻辑读写量，以及系统 CPU、I/O wait、内存、swap、线程数量和磁盘读写。

## 证据

`runtimes.json` 和 `runtimes/` 保存本次实际 runtime 配置。`workload.json` 保存来源/编组样本量。`deployment-before/` 保存被部署文件的原副本。

每档的 `workers-NNN/` 内包括：

- 三个独立压测数据库，保留成功、失败和所有尝试，不写原采集库。
- `stage.json`：计时边界、退出码及启动前资源状态。
- `metrics/*.jsonl`：每次 BEGIN、claim、counts 的墙钟耗时，以及原生完成/失败事件。
- `monitor.jsonl`：5 秒间隔的主机和备份 I/O 状态。
- `report.json`：有效完成数/小时、失败率、编组覆盖、原生耗时及数据库延迟统计。
- `logs/`：原 worker 输出；游戏日志在实验根目录 `logs/` 下。

BEGIN 的墙钟时间包含锁等待和线程调度时间，不能解释为精确的 SQLite 内部等待计时。CPU/内存为共享主机指标，须结合同时运行的其他进程判断。

## 执行入口

准备好包含 80 个闲置隔离 runtime 路径的 `runtimes.json` 后，在 `/data1` 项目根目录执行：

```bash
.venv/bin/python -u -m tools.one_off.benchmark_seed_workers prepare \
  --root data/seed-benchmark-20260919
.venv/bin/python -u -m tools.one_off.benchmark_seed_workers run \
  --root data/seed-benchmark-20260919 --workers 25 40 60 80 \
  --seconds 600 --warmup 60
```

已生成且带有匹配 manifest 的模板可恢复准备；已存在的阶梯目录不会覆盖。worker 异常退出时，当前档正常排空并保留证据，后续档停止，便于先诊断。这里没有放宽原生失败验收或修改锁竞争恢复策略。

## 解释边界

模板共 148,480 个 pending 任务，保证短时测量不会因队列耗尽停止；正式补采约 407 万场，队列增长和写入结果后的存储负担需要另外验证。`count-query-scaling.json` 是独立的内存缓存计数测试，不能替代原生战斗压测。

本实验按编组均衡取样，而正式补采的编组和来源数量并不均匀。各档之间可直接比较，但换算完整工期只能作为估计，还需要正式采集的持续吞吐验证。

各档包含重复输入，不能把同一构筑–编组–种子的多档结果当作多个独立种子。压测库不自动进入训练来源或正式补采统计。
