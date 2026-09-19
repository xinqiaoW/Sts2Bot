# 查看与刷新对战数据

本机页面通常为 `http://127.0.0.1:54260/`。当前已验证导出、批次、片段位置和服务信息以本机 `data/exports/current-view.json` 为准。页面是固定快照；浏览器刷新只重载页面，不会主动导出 01 数据库。

页面分别展示协议 3 的真实 v4 / 变异 v2、冻结的旧 8 秒批次和历史 2 秒批次。逐张升级、附魔和持久状态共同分组；同名不同状态不能合并。旧四种子批次未齐时显示 `1/4` 等进度，均值是暂定值。空批次隐藏，不代表删除其历史。

## 支持范围

`tools.prepare_combined_view` 只有 `--real-dir` 与 `--mutation-dir` 两个来源入口，不会自动纳入专项库或历史补采库。`tools.prepare_snapshot_view` 仍把 `planned_seed_count` 固定为 4，页面种子明细也按该数绘制；24 种子结果的进度和明细尚未适配。下面流程适用于原有看板刷新，不能用它验收全部新数据或判断补采是否完成。完整数量以数据库及导出清单为准。

## 生成候选快照

在 01 生产目录分别导出两库，每库使用只读事务，使该库计数、构筑和终局一致；两库不是同一个全局时间点：

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
