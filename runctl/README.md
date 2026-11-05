# RealRunEnv v1

用真实游戏推进整局，Python 决策、CombatSolver 执行战斗。默认模型全流程模式（`--policy model`，`decision_mode="all"`）的参数、选牌门槛和批量入口见 [机器人说明](../docs/autobot.md) 与 [配置规则](../docs/policy-configuration.md)。协议与隔离边界见 [设计说明](../docs/run-controller.md)。

## 独立环境

准备 0.111.0 游戏副本及独占用户目录；在该副本安装与 RunController 协议匹配的 CombatSolver 和相匹配的 RitsuLib。Linux 使用独立 Wine prefix，不要引用正在采集的 worker prefix。

```json
{
  "kind": "run_control",
  "game_dir": "/absolute/pilot/game",
  "data_dir": "/absolute/pilot/prefix/drive_c/users/pl/AppData/Roaming/SlayTheSpire2",
  "command": ["/absolute/wine", "SlayTheSpire2.slim.exe", "--main-pack", "SlayTheSpire2.pck", "--headless", "--disable-vsync", "--max-fps", "0", "--force-steam=off"],
  "env": {
    "WINEPREFIX": "/absolute/pilot/prefix",
    "WINEDEBUG": "-all",
    "WINEDLLOVERRIDES": "mshtml=",
    "COMBATSOLVER_HEADLESS": "1",
    "COMBATSOLVER_RUN_CONTROL": "1"
  },
  "log_path": "/absolute/pilot/logs/native.log"
}
```

替换为实际绝对路径；`data_dir` 必须与游戏该 prefix 中的 `user://` 对应。Windows 使用对应的独立用户数据目录与游戏命令。可选 `"combat_search_mode": "settings"` 读取该独立存档内的 CombatSolver 搜索设置（默认为 `"evaluation8s"`）。

## 运行

在仓库根目录执行：

```bash
python -m runctl --runtime /absolute/pilot/runtime.json \
  --episodes 2 --seed-prefix RUNCTL --policy-seed 0 \
  --output /absolute/pilot/reports/example
```

多局依次复用一个游戏进程，只有上一局成功完成清理才发送下一局。固定评测模式（`evaluation8s`）默认整局上限 3600 秒、每场战斗 120 秒、单次决策上限 300 秒（`--policy random-map` 默认 60 秒）；`combat_search_mode="settings"` 默认整局 14400 秒、每场战斗 1800 秒、模型单次决策 1800 秒（上限 3600 秒）。命令遇到失败即退出，写 `failure.json` 并保留原生现场，不把失败记为死亡。

```python
import json
from runctl import RealRunEnv

with RealRunEnv(json.load(open("runtime.json"))) as env:
    observation = env.reset("EXAMPLE", policy_seed=0, decision_mode="all")
    while observation.get("status") != "complete":
        observation = env.step(0)  # 选当前合法列表中的第一项
    print(observation["outcome"])
```

在长时间不提交动作或发生异常时，关闭环境会终止其拥有的进程组；不会终止其他游戏 worker。每局现场保存在独立 run ID 目录中。

## 验证

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python -m pytest tests/test_runctl.py -q
# 仅对独立试验目录运行：直接测试 C# 动作拒绝、超时与旧协议复用。
PYTHONPATH=. python tests/runctl_native.py --runtime /absolute/pilot/runtime.json \
  --output /absolute/pilot/reports/protocol
```
