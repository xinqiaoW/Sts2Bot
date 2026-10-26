# 查看与刷新对战数据

## 当前模拟器采集的实时查看页

```bash
.venv/bin/python -m tools.collection_view --directory .local/simulator-continuous
```

`--directory` 须指向实际采集实例，与采集命令保持一致；上例对应[持续采集](continuous-collection.md)的示例目录。省略该参数时，工具读取源码副本的 `data/collection-session.json` 中的 `project`，该文件须存在。默认地址为 `http://127.0.0.1:54261/`，可用 `--host`、`--port` 修改。远程访问可在本机执行 `ssh -N -L 54261:127.0.0.1:54261 user@server`，替换为实际 SSH 地址后打开本机同一端口。

页面只查看该实例的“真实构筑 / 普通变异 / 专项变异”三个库，不自动汇总其他实例或历史批次。界面的运行状态来自心跳文件；须结合时间戳和实际进程判断，重启前遗留的 `collecting` 不证明采集仍在运行。没有部署方提供的 `data/collection-session.json` 时，并发数等运行元数据可能显示为空。

页面支持净掉血分布、目标对照、来源 / 幕 / 敌人类型 / 卡牌和遗物搜索、逐场掉血与结果筛选，以及构筑、实际种子任务、附魔、持久状态、遗物计数、变异血缘和原始结果查看。筛选和所选构筑保存在地址栏，可直接复制链接。

采集库以 SQLite `mode=ro` 和 `query_only` 打开。查看页只写入独立的 `viewer/index.sqlite`，后台按尝试编号增量整理；首次整理未完成或来源不可用时显示明确提示。分布和均值只覆盖页面已整理的样本，库内完成数另外列出。页面约每 30 秒刷新，构筑详情打开时暂停自动刷新。

采集磁盘繁忙时可用 `--cache /another/local/disk/index.sqlite` 放置可重建索引。地址与缓存位置以启动参数为准，服务地址也写入启动日志。可选 `--localization /path/to/localization.json` 提供中文名称，缺失时显示 ID。

恢复或替换来源库，尤其是使用 `VACUUM INTO` 副本后，应停止查看服务，选择新的缓存路径重建索引。增量游标依赖源表 ROWID，不能假定恢复后的同一路径仍可复用旧缓存。

“净掉血”是战前血量减战后血量，包含治疗和死亡，不能把零净掉血直接当作无伤。目标均值受各目标的构筑分布影响，不能直接当作敌人难度排名。种子分母来自实际任务，不固定为 4；未整理齐时均值标为暂定。缺失回合不补成 0，战后血上限保留实值。字段一致性检查不会改变原始结果，也不代表模拟器与原生游戏已通过等价验证。

## 固定快照与兼容工具

静态页面只展示导出时的快照，浏览器刷新不会重新导出数据库。单库一致性导出使用：

```bash
.venv/bin/python -m tools.export_snapshot \
  --db /absolute/path/to/instance/db/real.sqlite \
  --output /absolute/path/to/new-export/collected-data.json.gz
```

工具输出 gzip 数据和 `source-manifest.json`，不自动生成 `quarantined-jobs.json`；旧组合页面所需的隔离任务清单须另行准备。多个库分别导出，不是同一全局时间点。

旧工具 `tools.prepare_combined_view` 仅接入真实和普通变异两个来源，还依赖既有指针、历史批次及本地化资源，不是空目录首次部署入口。`tools.prepare_snapshot_view` 仍将计划种子数固定为 4，不能用旧页面验收 24 种子的进度或全部补采数量。当前三个实例库优先使用实时查看页。

维护旧静态页面时，先保留已有导出，再生成候选页并检查批次、状态分组、均值和脚本错误，最后更新页面指针。`--freeze-previous` 仅用于明确封存协议批次；不同协议结果不拼成同一批次。页面更新无需重启采集进程。
