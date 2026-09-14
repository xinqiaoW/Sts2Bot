# 保留的旧汇总方法

`damage_model/store.py` 的 `Store.summaries()` 原用于最初随机构筑的父代选择，现按用户要求整段注释保留；源码注释指向本文件。旧 `sampling.py`、`collect_rounds.py` 和 CLI `seed/evolve` 已删除。当前一代变异由 `damage_model/mutations.py` 实现，规则见[一代变异](../mutations-8s.md)。

离线训练、页面导出、恢复和显式迁移工具仍有用途，不能仅凭采集循环不调用就删掉。`Build.family/generation/parent/mutation/split`、旧导入修订及目标范围兼容用于数据身份、重审和血缘划分，继续保留。`local_backup.py` 仍导入 `rental_backup.snapshot`。

清理不删除原始来源、数据库、模型、attempts 或故障证据。旧清理的详细验证保存在部署证据 `evidence/code-cleanup-20260910/`；不再在当前操作文档中保留临时审批过程、缓存文件流水账和过时测试计数。
