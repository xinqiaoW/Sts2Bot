"""Editable configuration cannot redefine the schema or detach Bot rollout knobs."""
import json

import pytest

from runctl import policy_config
from runctl.policy import BotPolicy
from train import reward_policy
from train.policy_defaults import BOT_DEFAULTS, REWARD_DEFAULTS, BOT_REWARD_KEYS
from test_reward_policy import FakeScorer


@pytest.mark.parametrize('module,loader,defaults', [
    (policy_config, policy_config.load_policy_config, BOT_DEFAULTS),
    (reward_policy, reward_policy.load_config, REWARD_DEFAULTS),
])
def test_editable_default_file_has_stable_schema_and_missing_defaults(tmp_path, monkeypatch, module, loader, defaults):
    path = tmp_path / 'policy.json'
    monkeypatch.setattr(module, 'DEFAULT_CONFIG', path)
    path.write_text('{"samples_per_parent": 11}')
    result = loader(None)
    assert result['samples_per_parent'] == 11
    assert result['rollout_max_upgrades'] == defaults['rollout_max_upgrades']
    path.write_text('{"sampls_per_parent": 11}')
    with pytest.raises(ValueError, match='Unknown'):
        loader(None)
    path.write_text('[]')
    with pytest.raises(ValueError, match='JSON object'):
        loader(None)


def test_shared_bot_values_win_and_reward_only_knobs_survive(tmp_path, monkeypatch):
    path = tmp_path / 'reward.json'
    path.write_text(json.dumps(dict(seed=42, samples_per_parent=9, cpu_threads=2,
        short_floor_weights=[2., 1.], rarity_weights=dict(Common=8., Uncommon=4., Rare=1.))))
    monkeypatch.setattr(reward_policy, 'DEFAULT_CONFIG', path)
    bot = BotPolicy(FakeScorer(), config=dict(seed=7341, samples_per_parent=12, keep_per_parent=3))
    assert all(bot.reward_config[k] == bot.config[k] for k in BOT_REWARD_KEYS)
    assert bot.reward_config['seed'] == 7341
    assert bot.reward_config['cpu_threads'] == 2
    assert bot.reward_config['short_floor_weights'] == [2., 1.]
    assert bot.reward_config['rarity_weights']['Common'] == 8.
    assert bot.reward_config['strict_features'] is False


def test_retired_crisis_key_in_default_file_is_warned_and_removed(tmp_path, monkeypatch):
    path = tmp_path / 'bot.json'
    path.write_text('{"crisis_boss_loss_fraction": 0.8, "crisis_boss_loss_threshold": 45}')
    monkeypatch.setattr(policy_config, 'DEFAULT_CONFIG', path)
    with pytest.warns(UserWarning, match='obsolete'):
        config = policy_config.load_policy_config()
    assert 'crisis_boss_loss_fraction' not in config
    assert config['crisis_boss_loss_threshold'] == 45


def test_defaults_do_not_leak_between_loads():
    config = reward_policy.load_config()
    config['rarity_weights']['Common'] = 100
    assert reward_policy.load_config()['rarity_weights']['Common'] == 9


def test_cli_uses_effective_cpu_setting_and_records_rollout_config(tmp_path, monkeypatch):
    import sys
    import torch
    import runctl.__main__ as cli
    import runctl.policy as policy

    reward_path = tmp_path / 'reward.json'
    reward_path.write_text('{"cpu_threads": 2}')
    monkeypatch.setattr(reward_policy, 'DEFAULT_CONFIG', reward_path)
    bot_path = tmp_path / 'bot.json'
    bot_path.write_text('{"seed": 173}')
    runtime = tmp_path / 'runtime.json'
    runtime.write_text('{"combat_search_mode": "settings"}')
    output = tmp_path / 'report'
    threads = []
    monkeypatch.setattr(torch, 'set_num_threads', threads.append)
    real_policy = policy.BotPolicy
    monkeypatch.setattr(policy, 'BotPolicy', lambda config: real_policy(FakeScorer(), config))

    class CompletedEnv:
        run_id = 'test-run'
        run_dir = tmp_path / 'native'
        def __init__(self, runtime):
            pass
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def reset(self, *args, **kwargs):
            return {'status': 'complete'}

    monkeypatch.setattr(cli, 'RealRunEnv', CompletedEnv)
    monkeypatch.setattr(sys, 'argv', ['runctl', '--runtime', str(runtime), '--output', str(output),
                                     '--policy-config', str(bot_path)])
    cli.main()
    assert threads == [2]
    assert json.loads((output / 'policy-config.json').read_text())['seed'] == 173
    effective = json.loads((output / 'reward-config.json').read_text())
    assert effective['seed'] == 173 and effective['cpu_threads'] == 2
