# tools / damage_model 代码清理记录

2026-09-10 检查了生产代码、测试、命令行入口、部署脚本和巡检引用。
不能仅凭“采集主循环没有调用”判定废弃：离线训练、数据展示、恢复和迁移仍需要这些工具。

## 已清理

- `damage_model/store.py` 的 `Store.summaries()`：最初给随机构筑的父代选择提供统计，现只剩两处旧测试调用；按用户要求整段注释保留，并移除不再使用的 `defaultdict` 导入。对应测试继续通过 `Store.rows()` 验证胜负样本保留与隔离样本不导出。
- `damage_model/sampling.py`、`tools/collect_rounds.py`、CLI 的 `seed/evolve` 早在提交 `c91f1c5` 中删除。本次不重新引入代码，只清理已无源文件的 `sampling` / `collect_rounds` 旧字节码。
- 本机 `tools/CatalogDump/bin`、`obj` 是可重新生成的构建产物。批量递归清理被自动审批审查拦截（返回 `blocked by policy`），本次保留这些目录及其他仍有源文件的 Python 缓存。改用明确文件路径清理孤立字节码；`Program.cs`、项目文件和已导出的游戏目录 JSON 保留。

清理范围限于上述代码、测试和可生成缓存；旧数据、模型、`.run` 原文、故障证据及现有部署记录均保留。

## 当前使用的模块

| 文件 | 用途 / 保留原因 |
| --- | --- |
| `damage_model/cli.py` | 导入、同步、采集、状态、训练和预测入口 |
| `run_source.py`、`source_backfill.py`、`run_import.py` | 下载真实来源、历史回填、重建战前输入及旧导入版本兼容 |
| `catalog.py`、`schema.py`、`target_scope.py` | 游戏规则、输入身份、同局同幕 f−2 到 f+2 目标范围；`Catalog.targets()` 仍用于合法性校验 |
| `store.py`、`worker.py`、`observation.py`、`resilience.py`、`provenance.py` | 队列、原生对战、标签校验、异常重试与隔离、冻结老师核验 |
| `mutations.py`、`priority_store.py`、`mutation_health.py` | 真实构筑的一代小／大变异、真实队列优先、变异巡检；这是 9 月 8 日启用的新流程 |
| `encoding.py`、`model.py`、`checkpoint_validation.py` | 离线模型训练、预测与验证；采集期间不自动训练，仍保留后续训练能力 |
| `tools/collect_continuous.py`、`collect_parallel.py` | 控制器和进程池；显式停止、可选训练等分支属于维护能力 |
| `tools/local_backup.py`、`rental_backup.py` | 当前 01 备份仍导入 `rental_backup.snapshot`；租用机回传入口留作运维工具 |
| `tools/export_snapshot.py`、`prepare_snapshot_view.py`、`prepare_combined_view.py` | 导出快照和准备新旧批次的数据页面 |
| `tools/view_payload.py`、`view_string_decoder.js`、`battles_view.html` | 页面数据压缩／还原和展示模板 |
| `tools/change_teacher.py`、`migrate_target_scope.py` | 显式离线迁移，有测试和部署脚本引用；不在采集过程中自动运行 |
| `tools/prepare_parallel_runtimes.py`、`prepare_wine_profile.py`、`CatalogDump/` | 重建运行环境和游戏目录所需工具 |

`Build.family / generation / parent / mutation / split` 既服务历史数据兼容，也服务当前变异血缘和训练划分，不能删除。
旧导入版本、旧目标范围的兼容分支保留，用于识别与重审历史来源，避免破坏已有输入身份或重复采集。

## 验证和部署

本次只退出未被生产路径调用的汇总方法。其余 Store 可执行 AST 必须与清理前一致；
既有标签、隔离、重试、变异和导入测试用于验证清理结果。01 隔离候选目录的完整测试为 286 passed；
Windows 定向测试为 138 passed、4 skipped，另有 3 项 Linux 专用进程／锁测试无法在 Windows 运行，均已在 01 通过。
01 同步代码时无需停止或重启采集进程，巡检摘要通过新增部署清单记录。
清理清单及验证结果保存在 `../../evidence/code-cleanup-20260910/`。
