# 全量 8 秒数据：Set Transformer

训练快照：2,966,659 条有效导出，去除跨库重复后 2,806,181 条，覆盖 14 个来源。2 秒数据单独保留。
按源局和变异血缘分组：训练 2,302,889 条，验证 169,696 条，测试 333,596 条；测试集 48,391 个构筑与目标组合。

模型参数量 352,514，最佳轮次 17，训练与产物生成耗时 1678.7 秒。按验证集 pair MAE 选取最佳权重。

| 指标 | 验证集 | 测试集 |
|---|---:|---:|
| pair MAE（HP） | 4.091067 | 4.148738 |
| pair RMSE（HP） | 6.563271 | 6.555894 |
| pair R² | 0.856539 | 0.861675 |
| 逐场加权 MAE（HP） | 6.535610 | 6.682282 |
| 死亡 Brier | 0.021208 | 0.021586 |
| 死亡 AUC | 0.979045 | 0.980390 |

pair 指标比较同一输入各战斗种子的平均掉血；逐场指标按种子数倒数加权。

| 测试后端 | 行数 | pair MAE（HP） | 死亡 Brier |
|---|---:|---:|---:|
| native-wine | 165,526 | 4.232838 | 0.021003 |
| standalone-managed-native | 168,070 | 3.831764 | 0.023783 |

原生与模拟器混合来源保留实验标记。旧 real 来源另有 153 条 SQLite 行无法读取，拒绝记录保存在来源缓存中。
已逐条核对全部预测的编号和标签，独立复算各划分指标，并重载权重抽测 24 个测试输入。

本机权重目录：`/data/pl/Sts2Bot-training-20261031/checkpoints/set_transformer`。本机选定模型入口：`checkpoints/train/selected`。
模型训练代码提交：`62a6532fb46744188904d4c253df182dce868641`。

```bash
.venv-train/bin/python -m train.predict \
  --checkpoint checkpoints/train/selected \
  --build build.json --target FLYCONID_NORMAL --max-hp 70
```

输入使用 `damage_model.schema.Build.to_dict()` 格式，目标须属于模型训练覆盖范围。
