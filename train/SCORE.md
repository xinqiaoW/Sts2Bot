# 给自动爬塔机器人调用的预期掉血评分

战后“三选一或跳过”的短期 + Boss rollout 选牌模块见 [REWARD_POLICY.md](REWARD_POLICY.md)。

默认加载 `checkpoints/train/selected`，复用已有 `train.predict.Predictor`。
输入是构筑、生命上限和敌人；输出是预期净掉血、满血死亡概率、评分及训练未见特征。
`score = -expected_hp_loss`，越大越好。模型条件为静默猎手 A10、满血开战、不使用药水、8 秒战斗求解。
不支持当前生命值输入，也不能用输出的死亡概率代表残血风险。
当前训练数据的生命上限均为 70；其他 `max_hp` 虽可输入，属于数值外推，程序会在 `warnings` 中标明。

## 直接运行

```bash
# 已准备好 48 个留出样例 + 12 个构筑改动，可编辑里面的 build / target 再跑
.venv-train/bin/python -m train.score \
  --input train/reports/20261101-score-examples/inputs.jsonl \
  --output /tmp/sts2-scores.jsonl

# 重新抽样、加载权重推理、生成与已有战斗记录的对照报告
.venv-train/bin/python -m train.score_examples \
  --output train/reports/20261101-score-examples
```

第二条命令需要 checkpoint 的 artifact.json 所指向的原始训练快照；第一条仅需模型目录、仓库 catalog/config 和输入文件。
运行环境为现有 `.venv-train`。默认 CPU；评分命令可传 `--device cuda:0`，`--strict` 拒绝训练未见的符号。

## JSONL 格式

每行一个对象，必填 `build`、`max_hp`，以及 `target` 或 `targets` 二选一：

```python
{
    "id": "candidate-1",       # 可选，保留到输出，便于关联候选
    "build": build.to_dict(),  # damage_model.schema.Build 格式
    "max_hp": 70,
    "target": "FLYCONID_NORMAL"
}
```

`build` 中完整保留 act_id、act、cards、relics（取得顺序与计数）、ancient_history、family 等字段。
不要把遗物计数、卡牌升级、附魔或持久状态丢掉。可参考已生成的 inputs.jsonl。

若要综合多个敌人，把 `target` 换成 `"targets": {"FLYCONID_NORMAL": 3, "BYGONE_EFFIGY_ELITE": 1}`。
权重会归一化，此例分别占 75% 和 25%，输出是单次遭遇的加权平均，不是连续打完整条路线的累计掉血。
所有敌人必须在该构筑区域的模型覆盖范围内；没有默认假设地图遭遇分布。
比较候选构筑时应固定同一套敌人和权重。

## Python 调用

```python
from train.score import BuildScorer

scorer = BuildScorer()  # 机器人启动时加载一次
results = scorer.score_many([
    {"id": "before", "build": before.to_dict(), "max_hp": 70,
     "target": "FLYCONID_NORMAL"},
    {"id": "after", "build": after.to_dict(), "max_hp": 70,
     "target": "FLYCONID_NORMAL"},
])
gain = results[1]["score"] - results[0]["score"]  # 正数表示预测改善
```

## 首次试跑

查看 [60 个样例报告](reports/20261101-score-examples/report.md)，包括完整牌组、遗物、每次已有战斗掉血和模型预测。
48 对留出样例按区域和敌人类别等额随机抽取，MAE 为 5.54 HP，最大误差 24.36 HP；整体测试集 MAE 为 4.15 HP。
12 个改动仅有模型预测，没有新增战斗标签。其中两次升级打击后预测掉血反而上升 0.31 / 0.09 HP，说明模型没有保证升级收益的单调性。
可以先用来粗排候选；小差值不宜当成已验证的决策收益。报告没有重新运行战斗模拟器。
