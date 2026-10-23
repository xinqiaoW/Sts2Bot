# 01 运行环境

SSH 别名为 `01`，源码维护目录是 `/data2/pl/ImageTask/wxq/Projects/Sts2Bot`。模拟器实例由 `--directory` 指定，默认位于源码目录的 `.local/simulator-collect/`；历史 Wine 执行与数据副本位于 `/data1/pl/ImageTask/wxq/Projects/Sts2Bot`。切换源码分支不会同步其他副本或重启进程。

## 模拟器运行条件

当前采集使用 Linux .NET 独立进程，无需启动 Wine 或 Godot 游戏进程。需要项目 Python 3.11+ 环境，以及另行提供的冻结发布包、游戏资源和 .NET。发布包通过 `--bundle`、`STS2_SIMULATOR_BUNDLE` 或本机 `configs/simulator.json` 选择；这些本机资源不随 checkout 提供，详见[模拟器采集](simulator-collection.md)。

| 资源 | 位置或配置来源 |
| --- | --- |
| Python | 仓库中的 `.venv/bin/python`；本机环境须另行准备 |
| .NET、游戏程序集与依赖 | 发布包 `runtime-template.json` 指定的路径 |
| 宿主、教师、目录及采集策略 | 冻结发布包的 `host/`、`teacher.json`、`catalogs/`、`configs/` |
| 解锁状态 | 发布包的 `progress-snapshot.json` |
| 队列、来源与日志 | 实例目录的 `db/`、`source/`、`logs/` |
| worker 隔离 | 实例中的 `runtime-*.json`、`worker-*/` |

采集使用 CPU，每场搜索为 DOP 1。可用资源随共享负载变化，启动前检查主机余量及用户 cgroup 的内存、线程限额。训练使用独立环境，见[训练说明](../train/README.md)。

## 部署与恢复

模拟器发布包固定游戏、求解器、宿主、进度快照和策略身份；仅更新仓库中的同名配置不会更新发布包。代码与匹配资源准备好后，启动时核对发布清单和 runtime。已有实例还核对发布包路径、摘要与 worker 数，更换其中任一项应使用新实例。

恢复前核对实例数据库、配置、实际进程和锁，处理停止原因，再接续原命令。完整备份还须保留实例元数据与发布资源；旧备份工具不会自动收齐模拟器布局，见[持续采集](continuous-collection.md)。

## 历史 Wine 后端

以下资源仅用于旧原生采集与独立 RunController 试验：

| 资源 | 历史执行副本中的位置 |
| --- | --- |
| 游戏与协议 3 采集器 | `.runtime/game-card-state-v3/` |
| Wine 11.0 | `.runtime/wine/root/opt/wine-stable/bin/wine` |
| 隔离环境 | runtime 的 `env.WINEPREFIX` |
| 协议数据与日志 | runtime 的 `data_dir`、`log_path` |
| 采集 runtime 列表 | `data/collection-session.json` 的 `runtimes` |
| 补采 runtime 列表 | 对应运行目录的 `runtimes.json` |

每个 runtime 独占 Wine prefix、用户数据、存档、协议文件和日志，正常采集与补采不能复用。`tools.prepare_parallel_runtimes`、`tools.prepare_wine_profile` 用于准备；复制 prefix 前须确认模板没有活动游戏或 Wine server。

Windows 游戏经 Wine 执行，`SlayTheSpire2.slim.exe` 配合原 PCK 和游戏程序集启动：

```text
SlayTheSpire2.slim.exe --main-pack SlayTheSpire2.pck --headless --disable-vsync --max-fps 0 --force-steam=off
```

环境使用 `COMBATSOLVER_HEADLESS=1`、`WINEDEBUG=-all`、`WINEDLLOVERRIDES=mshtml=`，不能禁用 `mscoree`。隔离存档关闭教学弹窗；`override.cfg` 的 `worker_pool/max_threads=8` 限制 Godot 辅助线程，与搜索 DOP 1 无关。

旧副本部署须同步相互依赖的源码与采集配置，保留本机路径和数据，并核对 `configs/teacher.json` 与游戏、采集器摘要。历史 real-v3 / mut-v1 训练仍需完整标签或冻结缓存，`prior_collected_inputs` 去重索引不能代替标签。`evidence/` 中的迁移、故障脚本仅供取证。补采与整局入口分别见[补采工具](../tools/one_off/README.md)、[RunController](../runctl/README.md)。
