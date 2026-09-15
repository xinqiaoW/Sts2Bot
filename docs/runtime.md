# 01 运行环境

当前生产目录为 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot`，SSH 别名 `01`。旧 `/data2/pl/ImageTask/wxq/Projects/Sts2Bot` 曾发生文件系统损坏，保留其中的历史库与 Git 工作副本不代表允许从那里恢复采集。

## 运行资源

Ubuntu 22.04，CPU 为双路 EPYC 7763、256 逻辑核，约 251 GiB 内存。可用 CPU、内存、GPU 随共享主机负载变化，不能把一次观测写成固定资源余量。采集使用 CPU；25 个独立游戏进程内的搜索各为 DOP 1。训练用独立环境和明确选择的 GPU，见[训练说明](../train/README.md)。

| 资源 | 生产位置 |
| --- | --- |
| Python | `.venv/bin/python`，指向既有 py311 环境 |
| 游戏与协议 3 采集器 | `.runtime/game-card-state-v3/` |
| Wine 11.0 | `.runtime/wine/root/opt/wine-stable/bin/wine` |
| 第一个隔离环境 | `.runtime/prefix-smoke/` |
| 其他隔离环境 | `.runtime/prefix-worker-01/` 至 `prefix-worker-24/` |
| runtime 配置 | `configs/runtime-wine-pilot.json` 及 session 中列出的 worker 配置 |

每个 runtime 必须有独立的 `WINEPREFIX`、`data_dir`、存档、协议文件和日志。实际完整路径从 runtime 配置读取，不复制运行中的 prefix 作为扩容模板。`tools.prepare_parallel_runtimes`、`tools.prepare_wine_profile` 用于明确的环境准备，不是日常恢复命令。

运行的是 Windows 游戏经 Wine 执行。`SlayTheSpire2.slim.exe` 是去除调试信息的独立副本，原 PCK 和游戏程序集保持；不是 Linux 原生游戏。启动参数：

```text
SlayTheSpire2.slim.exe --main-pack SlayTheSpire2.pck --headless --disable-vsync --max-fps 0 --force-steam=off
```

环境包含 `COMBATSOLVER_HEADLESS=1`、`WINEDEBUG=-all`、`WINEDLLOVERRIDES=mshtml=`，不能禁用 `mscoree`。隔离存档关闭教学弹窗。游戏目录 `override.cfg` 中 `worker_pool/max_threads=8` 限制 Godot 辅助线程，和求解器 DOP 1 是不同设置。

## 工作副本与生产部署

本机采集工具副本通常位于 `C:/Users/www/Documents/Sts2DamageModel`；文档分支是 `docs/corrections`。Git 分支只表达源码版本，线上实际口径还依赖 session、配置、目录导出、部署清单及游戏/采集器摘要。游戏、Wine、数据库和模型不随普通源码 checkout 自动获得。

`feat/mutation-selection-strategy` 已补入生产版本兼容、历史回补和工作者续接代码，并增加三队列采集。恢复命令仍须在已部署并通过校验的 `/data1` 副本执行；仅切换 Git 分支不会自动切换生产进程。

迁移只带走必要生产文件。旧协议 2 的真实 v3、变异 v1 历史数据库，以及部分旧下载页和 Git 元数据仍在旧目录；不能默认它们已在 `/data1` 齐备。冻结训练缓存需先恢复到健康路径并核验，之后才可显式复用，见[训练快照准备](../train/README.md)。

恢复前核对 `data/collection-session.json`、`data/active-collection.json`、runtime 路径、`configs/teacher.json` 与实际进程/锁。不要重放 `evidence/` 中已执行的一次性迁移脚本。持续采集与备份操作见[持续采集](continuous-collection.md)。
