# 待清理项

## `tools/collect_continuous.py` 内置训练分支

- **现状**：`Controller` 仍保留非 `--collect-only` 下的 `initial_samples`（默认 6080）、`initial_output`、`output_root`、`validate_or_train` 及 `.continuous.progress.json` 中的 `initial_samples` 一致性校验。
- **目标**：采集控制器仅负责队列补充与采集调度，模型训练统一由 `train/` 独立流程处理，后续可移除控制器内的旧训练与检查点验证分支。