# 待清理

## 控制器内训练的初始面板

`tools/collect_continuous.py` 里，`initial_samples` 是为了收集之后直接进入训练，我们希望目前的代码只处理收集逻辑而不包括训练，所以相关内容可以进行清理

旧行为：待领取任务为 0 时，完成数正好等于 `initial_samples`（默认和沙箱都是 6080）就把模型写到 `initial_output`（`checkpoints/v1`）；完成数更大时写到 `output_root/samples-00000xxxx`。进度文件 `*.continuous.progress.json` 记下第一次的 `initial_samples`，重启时数字不一致就拒绝启动，避免旧检查点目录和新规则对不上。