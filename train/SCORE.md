# 预期掉血评分（`train.score`）

短期 + 长期 rollout 的奖励/选牌决策模块见 [REWARD_POLICY.md](REWARD_POLICY.md)。

默认加载 `checkpoints/train/selected`，复用 `train.predict.Predictor`。输入是构筑、生命上限和敌人；输出是预期净掉血、满血死亡概率、评分及训练未见特征。`score = -expected_hp_loss`，越大越好。模型条件为静默猎手 A10、满血开战、不使用药水、8 秒战斗求解。不支持当前生命值输入，也不能用输出的死亡概率代表残血风险。当前训练数据的生命上限均为 70；其他 `max_hp` 虽可输入，属于数值外推，程序会在 `warnings` 中标明。

## 直接运行

```bash
# 对输入 JSONL 逐行计算构筑评分
.venv-train/bin/python -m train.score \
  --input inputs.jsonl \
  --output /tmp/sts2-scores.jsonl

# 从原始训练快照留出集抽样并生成对照报告
.venv-train/bin/python -m train.score_examples \
  --output /tmp/score-examples
```

第二条命令需要 checkpoint 的 `artifact.json` 所指向的原始训练快照；第一条仅需模型目录、仓库 `catalogs/` 与 `configs/` 及输入文件。默认使用 CPU；可传 `--device cuda:0`，`--strict` 拒绝训练未见的符号。

## JSONL 格式

每行一个对象，必填 `build`、`max_hp`，以及 `target` 或 `targets` 二选一：

```python
{
    "id": "candidate-1",       # 可选，保留到输出，便于关联候选
    "build": build.to_dict(),  # damage_model.schema.Build 格式
    "max_hp": 70,
    "target": "FLYCONID_NORMAL",
    # "encounter_act_id": "HIVE",  # 可选，投影到当前幕或下一幕遭遇（不伪造未来先古奖励）
}
```

`build` 中完整保留 `act_id`、`act`、`cards`、`relics`（取得顺序与计数）、`ancient_history`、`family` 等字段，不得丢弃遗物计数、卡牌升级、附魔或持久状态。

若要综合多个敌人，将 `target` 换成 `"targets": {"FLYCONID_NORMAL": 3, "BYGONE_EFFIGY_ELITE": 1}`。权重会自动归一化，输出是单次遭遇的加权平均，不是连续路线的累计掉血。所有敌人必须在该区域（或 `encounter_act_id` 投影区域）的模型覆盖范围内。比较候选构筑时应固定同一套敌人和权重。

## Python 调用

```python
from train.score import BuildScorer

scorer = BuildScorer()  # 启动时加载一次并复用
results = scorer.score_many([
    {"id": "before", "build": before.to_dict(), "max_hp": 70,
     "target": "FLYCONID_NORMAL"},
    {"id": "after", "build": after.to_dict(), "max_hp": 70,
     "target": "FLYCONID_NORMAL"},
])
gain = results[1]["score"] - results[0]["score"]  # 正数表示预测改善
```
