# 策略与配置架构整理说明

本页记录 Python Bot、模型评分入口、更新脚本及配置 schema 的统一约束与已知近似边界。当前参数定义见 [当前评分与配置规则](policy-configuration.md)。

## 统一机制

| 模块 | 职责与约束 |
| --- | --- |
| `train/policy_defaults.py` | 维护 `REWARD_DEFAULTS`、`BOT_DEFAULTS` 与共有键 `BOT_REWARD_KEYS`；JSON 配置仅作为覆盖层，缺项自动补齐，未知键报错 |
| `runctl/card_search.py` | 统一正常与危机搜索深度规划；跨幕评估使用 `post_boss_rollout_depth`，战后奖励固定深度优先 |
| `train/live_state.py` | 集中实机卡牌与遗物状态转换，供 `runctl` 与 `train.advisor_service` 共享 |
| `tools/install_bot_update.py` | 统一 Windows Bot 增量更新清单，支持平铺补丁与完整包目录，仅补齐缺失配置键并保留用户已有参数 |
| `policy-config.json` / `reward-config.json` | 每次 Bot 运行在报告目录同时保存最终 Bot 配置与合并后的实际 rollout 评分配置 |

## 保留的兼容逻辑

- 旧输入未提供当前 HP（`budget_hp`）时，固定近期掉血阈值（`short_strength_loss_threshold`）与精英掉血阈值（`elite_target_loss_threshold`）作为 legacy 兼容回退，并在日志中显式标注。
- `crisis_boss_loss_threshold` 保留字段名，但比较的长期目标可为精英或 Boss，日志通过 `crisis_basis`、`crisis_target_room`、`projected_long_loss` 标明实际口径。
- 已废弃的 `crisis_boss_loss_fraction` 在加载配置时发出警告并忽略，防止旧配置文件报错中止。
- `train.advisor_service` 保留对 `train.live_state` 转换函数的兼容导出；`tools/install_scoring_horizon_update.py` 转发至 `tools/install_bot_update.py`。

## 已知策略近似边界

- **Rollout 尾部与升级约束**：`leaf_bottom_fraction` 来自每层择优剪枝后的保留叶子，不代表未剪枝未来的真实最差分布；`rollout_max_upgrades` 升级分支未受真实地图篝火数量与休息代价约束。
- **跨幕评估血量**：Boss 战后跨幕评分使用收到的当前 HP，未预先计入幕间过渡回血；长期目标使用下一幕公开池均值，真实牌组库存不变。
- **地图信息粒度**：Bot 使用完整公开地图节点，人工面板（`train.advisor_service`）使用按层汇总的房间类型分布；短期窗口跨过弱怪池边界或连续双 Boss 时两者存在输入粒度近似。
- **路线规划**：`runctl/route_policy.py` 中篝火收益按回血启发式近似，不是整幕精确动态规划。
- **生存预算与危机扩搜独立**：生存预算（切换长短期权重与精英/Boss 目标）基于未修改的当前构筑；危机扩搜（`crisis`）基于普通 rollout 所有候选中的最佳长期预期掉血。
- **满血无药模型假设**：底层预期掉血模型以 70/70 满血、无药水、8 秒求解标签训练，当前 HP 与药水库存仅通过外层策略启发式参与决策。
