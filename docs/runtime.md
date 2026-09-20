# 01 运行环境

SSH 别名为 `01`。源码维护目录是 `/data2/pl/ImageTask/wxq/Projects/Sts2Bot`，执行与数据目录是 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot`。代码修改在源码分支完成，部署后才影响执行副本。

## 运行资源

Ubuntu 22.04，双路 EPYC 7763、256 逻辑核，约 251 GiB 主机内存。采集使用 CPU，每场搜索为 DOP 1。可用资源随共享负载变化，启动前同时检查主机余量和用户 cgroup 的内存、线程限额；不能把一次观测当成固定可用容量。训练使用独立环境，见[训练说明](../train/README.md)。

| 资源 | 执行副本中的位置 |
| --- | --- |
| Python | `.venv/bin/python` |
| 游戏与协议 3 采集器 | `.runtime/game-card-state-v3/` |
| Wine 11.0 | `.runtime/wine/root/opt/wine-stable/bin/wine` |
| 隔离环境 | 各 runtime 配置中的 `env.WINEPREFIX` |
| 协议数据与日志 | 各 runtime 配置中的 `data_dir`、`log_path` |
| 正常采集 runtime 列表 | `data/collection-session.json` 的 `runtimes` |
| 一次性补采 runtime 列表 | 对应运行目录的 `runtimes.json` |

每个 runtime 必须独占 Wine prefix、用户数据目录、存档、协议文件和日志。正常采集与补采不能复用同一个 runtime。`tools.prepare_parallel_runtimes`、`tools.prepare_wine_profile` 用于环境准备；复制 prefix 前须确认模板没有活动游戏或 Wine server。

运行的是 Windows 游戏经 Wine 执行。`SlayTheSpire2.slim.exe` 是去除调试信息的独立副本，原 PCK 和游戏程序集保持。启动参数：

```text
SlayTheSpire2.slim.exe --main-pack SlayTheSpire2.pck --headless --disable-vsync --max-fps 0 --force-steam=off
```

环境包含 `COMBATSOLVER_HEADLESS=1`、`WINEDEBUG=-all`、`WINEDLLOVERRIDES=mshtml=`，不能禁用 `mscoree`。隔离存档关闭教学弹窗。游戏目录 `override.cfg` 的 `worker_pool/max_threads=8` 限制 Godot 辅助线程，和求解器 DOP 1 是不同设置。

## 部署与恢复

Git 分支只表达源码版本。游戏、Wine、数据库、模型和本机 runtime 配置不随普通 checkout 自动获得；切换分支也不会重启运行中的进程。

部署时同步相互依赖的源码与采集配置，保留执行副本自己的 runtime 路径和数据。核对部署清单、`configs/teacher.json`、游戏与采集器摘要，记录实际部署版本。恢复前再核对 session、活动库、进程和锁，避免用旧路径启动另一套采集。

历史 real-v3 / mut-v1 的完整标签与冻结训练缓存应按实际文件或快照清单定位。新版库保留的 `prior_collected_inputs` 可用于补采去重，但不能替代训练导出所需的旧标签；训练前须准备完整数据库或已验证缓存。

持续采集操作见[持续采集](continuous-collection.md)，历史种子补采见[一次性补采](../tools/one_off/README.md)。`evidence/` 中的迁移或故障处理脚本是历史证据，不应作为日常恢复入口直接重放。
