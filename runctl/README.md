# RealRunEnv v1

用真实游戏推进整局，Python 选择地图路线，CombatSolver 执行战斗。完整范围与限制见 [设计说明](../docs/run-controller.md)。

## 独立环境

准备 0.111.0 游戏副本及独占用户目录；在该副本安装与 RunController 协议匹配的 CombatSolver 和相匹配的 RitsuLib。Linux 使用独立 Wine prefix。不要引用正在采集的 worker prefix。

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

替换为实际绝对路径；`data_dir` 必须与游戏该 prefix 中的 `user://` 对应。Windows 使用对应的独立用户数据目录与游戏命令。当前原生验证平台为 Linux/Wine，Windows Python 逻辑共用，原生 Windows 整局尚需单独验证。

## 运行

在仓库根目录执行：

```bash
python -m runctl --runtime /absolute/pilot/runtime.json \
  --episodes 2 --seed-prefix RUNCTL --policy-seed 0 \
  --output /absolute/pilot/reports/example
```

多局依次复用一个游戏进程，只有上一局成功完成清理才发送下一局。默认一局最长 3600 秒、每场战斗 120 秒、地图动作等待 60 秒。命令遇到失败即退出，写 `failure.json` 并保留原生现场，不把失败记为死亡；重新启动会产生新的尝试 ID。

```python
import json
from runctl import RealRunEnv

with RealRunEnv(json.load(open("runtime.json"))) as env:
    observation = env.reset("EXAMPLE", policy_seed=0)
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

协议测试使用模拟的文件对端；它证明客户端隔离及失败处理，不证明原生游戏规则等价。原生整局与旧单场协议需要分别通过实际试跑。
