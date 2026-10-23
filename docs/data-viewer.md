# 查看与刷新对战数据

## 当前模拟器采集的实时查看页

```bash
.venv/bin/python -m tools.collection_view --directory .local/simulator-continuous
```

`--directory` 须指向实际采集实例，与采集命令保持一致；上例对应[持续采集](continuous-collection.md)的示例目录。默认地址为 `http://127.0.0.1:54261/`，可用 `--host`、`--port` 修改。远程访问可在本机执行 `ssh -N -L 54261:127.0.0.1:54261 01`，再打开本机同一地址。三个当前队列分别显示为“真实构筑 / 普通变异 / 专项变异”，不会混入旧的原生采集批次。

页面支持净掉血分布、目标对照、来源 / 幕 / 敌人类型 / 卡牌和遗物搜索、逐场掉血与结果筛选，以及构筑、实际种子任务、附魔、持久状态、遗物计数、变异血缘和原始结果查看。筛选和所选构筑保存在地址栏，可直接复制链接。

采集库以 SQLite `mode=ro` 和 `query_only` 打开。查看页只写入独立的 `viewer/index.sqlite`，后台按尝试编号增量整理；首次整理未完成或来源不可用时显示明确提示。分布和均值只覆盖页面已整理的样本，库内完成数另外列出。页面约每 30 秒刷新，构筑详情打开时暂停自动刷新。

采集磁盘繁忙时可用 `--cache /另一块本机盘/index.sqlite` 放置可重建索引。地址与缓存位置以启动参数为准，服务地址也写入启动日志。工具不生成服务进程清单；可选 `--localization /path/to/localization.json` 提供中文名称，缺失时显示 ID。缓存可重建。

“净掉血”是战前血量减战后血量，包含治疗和死亡，不能把零净掉血直接当作无伤。目标均值受各目标的构筑分布影响，不能直接当作敌人难度排名。种子分母来自实际任务，不固定为 4；未整理齐时均值标为暂定。缺失回合不补成 0，战后血上限保留实值。字段一致性检查不会改变原始结果，也不代表模拟器与原生游戏已通过等价验证。

## 原有固定快照页面

本机页面通常为 `http://127.0.0.1:54260/`。当前已验证导出、批次、片段位置和服务信息以本机 `data/exports/current-view.json` 为准。页面是固定快照；浏览器刷新只重载页面，不会主动导出 01 数据库。

页面分别展示协议 3 的真实 v4 / 变异 v2、冻结的旧 8 秒批次和历史 2 秒批次。逐张升级、附魔和持久状态共同分组；同名不同状态不能合并。旧四种子批次未齐时显示 `1/4` 等进度，均值是暂定值。空批次隐藏，不代表删除其历史。

## 旧快照工具的支持范围

`tools.prepare_combined_view` 只有 `--real-dir` 与 `--mutation-dir` 两个来源入口，不会自动纳入专项库或历史补采库。`tools.prepare_snapshot_view` 仍把 `planned_seed_count` 固定为 4，页面种子明细也按该数绘制；24 种子结果的进度和明细尚未适配。下面流程适用于原有看板刷新，不能用它验收全部新数据或判断补采是否完成。完整数量以数据库及导出清单为准。

## 生成候选快照

在 01 的历史原生执行目录分别导出两库，每库使用只读事务，使该库计数、构筑和终局一致；两库不是同一个全局时间点：

```bash
cd /data1/pl/ImageTask/wxq/Projects/Sts2Bot
.venv/bin/python -m tools.export_snapshot --db data/collection-real-runs-v4.sqlite --output data/exports/view-real-<stamp>/collected-data.json.gz
.venv/bin/python -m tools.export_snapshot --db data/collection-mutations-v2.sqlite --output data/exports/view-mutation-<stamp>/collected-data.json.gz
```

将两份 gzip、各自 `source-manifest.json` 和一致的隔离任务清单 `quarantined-jobs.json` 保存到两个新的本机目录，并准备与游戏目录匹配的 `localization.json`。不要覆盖上一次已验证导出。在本机采集工具副本执行：

```bash
python tools/prepare_combined_view.py --real-dir <新真实目录> --mutation-dir <新变异目录> --pointer data/exports/current-view.json
```

工具沿用旧编号、本地化和历史批次，校验压缩内容、字段、种子、终局及旧结果保留，并核对隔离任务未进入结果。输出包括 `candidate.html`、`preservation.json`、`candidate-pointer.json`；**不会直接更新 current-view 指针**。

此组合工具依赖已有指针的 `label_reference`、`comparison_views`、导出目录和旧批次资源，目前还固定校验两批历史 2 秒数据的 72,959 / 4,856 场。它是现有看板的刷新工具，不是空目录首次部署入口。资源缺失时先恢复已验证文件，不改断言绕过保留检查。单批准备入口 `tools/prepare_snapshot_view.py` 的 `--input-dir`、`--fragment`、`--previous`、`--comparison-view` 与 `--standalone` 可用于独立候选页。

## 发布到本机页面

先用候选页检查批次切换、构筑/目标选择、完整和未齐种子的均值、附魔/持久状态、变异血缘及页面脚本错误，再更新已验证指针。发布时读取指针定位现有服务；若服务启动时缓存完整 HTML，需仅重载或重启该页面服务并核对端口和内容。采集进程无需重启。

`--freeze-previous` 只用于明确切换协议批次：先完整导出并核对即将封存的旧两库，再将它们作为独立历史视图接入。日常刷新不使用此参数，也不能把旧协议结果和新任务拼成同一采集批次。
