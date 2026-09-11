# 对战数据查看页面

2026-09-11：看板及 JSONL 增加逐张持久状态；同名不同疯狂科学效果/进度不可合并。新批次尚未产出结果时隐藏空选项，单种子结果仍显示 1/4，均值标为暂定。跨协议刷新时，先完成旧 v3/v1 两个库的最后一次导出和历史保留核验，再以 `prepare_combined_view.py --freeze-previous` 接入 v4/v2；旧 8 秒数据与新协议保持独立。普通后续刷新不用此参数。详见 [卡牌状态适配](card-state.md)。

2026-09-06附魔/计数扩展后：页面新增批次选择，分别展示 `collection-real-runs-v2.sqlite` 的新协议数据与旧真实构筑批次的4,856场终局。逐张附魔显示在卡牌名称旁，卡组来源展开后显示源局及战前层数；各构筑的全部同幕目标包括尚无结果的编组。统计中的目标数量仅计已经产生结果的编组。

当前指针仍为 `data/exports/current-view.json`。更新v2快照时，用同一批次前次view作为`--previous`，用旧批次view作为`--comparison-view`，并传`--dataset-label`。不能把两个协议批次按相同卡组与种子直接混成一个四种子面板。卡牌附魔ID/数值与升级必须一起分组。旧随机数据仍保留在历史快照和原库。

当前页面位于 `http://127.0.0.1:54260/`（`/index.html` 也可），由本机隐藏的 visualize `render.py --serve --port 54260` 进程提供。源片段为 `C:/Users/www/.codex/visualizations/2026/09/05/01a070e9-dfaa-78d3-a9d1-46dc22fd85a0/collected-battles.html`。

当前已验证快照、导出目录和页面进程 PID 记录在本机 `data/exports/current-view.json`。2026-09-06 13:17:04 更新至 13,852 场、165 种配置；新目录 `data/exports/snapshot-20260906-131704/`，上一版 9,941 场的结果和 118 个配置编号逐一核对保留。更新数据后，浏览器需重新载入页面。以下 12:53 记录为历史版本，后续刷新应以前述指针所指的 `view-data.json` 作为 `--previous`，并在浏览器验证通过后更新指针。

2026-09-06 12:53:51 北京时间快照：9,941 场有效原生终局、118 种卡组与遗物配置、42 个目标编组。比 09:35 的 7,052 场多 2,889 场；旧结果所有已导出字段和 84 个旧配置的浏览编号逐一核对相同。新结果包含采集机器，原始机器标签缺失的历史结果注明 `01 (before host tagging)`。这是一份快照，网页刷新不会主动重新导出服务器数据库。

新导出在 `data/exports/snapshot-20260906-rental/`；旧导出仍在 `data/exports/snapshot-20260906/`，其中保存了旧片段 `collected-battles.html`。新压缩包 `silent-battles-9941-20260906.zip` 包含逐场 JSONL、配置/目标聚合、中文名字、卡组、遗物计数及来源 manifest。2,485 个配置/目标组合已完成四种子，另一个组合完成一种子；界面明确显示部分采集状态。

## 再次更新

在当前采集服务器使用只读事务导出，事务中的计数、成功终局和构筑保持一致，不停止采集、不修改任何任务：

```sh
.venv/bin/python -m tools.export_snapshot --db data/collection-horizon.sqlite --output data/exports/view-latest/collected-data.json.gz
```

将 gzip 和同目录 `source-manifest.json` 下载到新的本机导出目录，复制既有 `localization.json`，再执行：

```sh
python tools/prepare_snapshot_view.py --input-dir <新导出目录> --fragment <现有片段绝对路径> --previous <前一版导出目录>/view-data.json
```

准备器校验 SHA-256、终局数量、种子重复、满血边界和压缩包内容；沿用旧配置编号，默认展示最近完成对战的配置/目标。`render.py` 启动时缓存完整文档，更新片段后必须核实并重启该页面的服务进程，使用同一端口。无需重启或修改服务器采集进程。

本次用已安装 Edge / Playwright 验证：页面计数和时间、配置与目标切换、原样本 35.5 血均值、新增双无色牌构筑、升级牌标记、全部目标表、390px 页面无横向溢出、无页面脚本异常。QA 文件位于上述片段目录，命名 `latest-view-*`。
