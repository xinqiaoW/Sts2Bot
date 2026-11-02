import json
from pathlib import Path

import pytest

from tools.install_scoring_horizon_update import SOURCES, CONFIGS, NATIVE, install


def installation(tmp_path):
    source, target, bot = (tmp_path / name for name in ('patch', 'service', 'bot'))
    game = tmp_path / 'actual-custom-game'
    mod = game / 'mods/CombatSolver'
    mod.mkdir(parents=True)
    for name in SOURCES:
        p = source / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('# updated\n')
        if name != 'train/scoring_horizon.py':
            p = target / name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text('# previous\n')
    for name in CONFIGS:
        p = source / name; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(dict(samples_per_parent=64, post_boss_rollout_depth=3)))
        p = target / name; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(dict(samples_per_parent=32, weak_short_weight=.8)))
    for name in NATIVE:
        p = source / 'CombatSolver' / name; p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(dict(id='CombatSolver', version='0.30.9')) if name.endswith('.json') else 'new-native')
        (mod / name).write_text('old-native')
    bot.mkdir()
    (bot / 'runtime.json').write_text(json.dumps(dict(kind='run_control', game_dir=str(game), action_timeout_seconds=2400)))
    return source, target, bot, mod


def test_pair_installs_into_actual_runtime_game_and_preserves_config(tmp_path):
    source, target, bot, mod = installation(tmp_path)
    runtime = (bot / 'runtime.json').read_bytes()
    backup = install(source, target, bot)
    for name in SOURCES:
        assert (target / name).read_bytes() == (source / name).read_bytes()
    assert (backup / 'advisor-service/runctl/policy.py').read_text() == '# previous\n'
    assert (backup / 'CombatSolver/CombatSolver.dll').read_text() == 'old-native'
    assert (mod / 'CombatSolver.dll').read_text() == 'new-native'
    assert not (bot / 'game').exists()
    assert (bot / 'runtime.json').read_bytes() == runtime
    for name in CONFIGS:
        assert json.loads((target / name).read_text()) == dict(samples_per_parent=32, weak_short_weight=.8, post_boss_rollout_depth=3)


def test_missing_native_source_fails_before_any_write(tmp_path):
    source, target, bot, mod = installation(tmp_path)
    (source / 'CombatSolver/CombatSolver.dll').unlink()
    with pytest.raises(FileNotFoundError):
        install(source, target, bot)
    assert (target / 'runctl/policy.py').read_text() == '# previous\n'
    assert (mod / 'CombatSolver.dll').read_text() == 'old-native'
    assert not (target / 'update-backups').exists()


def test_potion_priority_default_is_added_but_custom_order_is_preserved(tmp_path):
    source, target, bot, _ = installation(tmp_path)
    source_config = source / 'configs/bot-policy.json'
    defaults = json.loads(source_config.read_text())
    defaults['potion_priority'] = ['FAIRY_IN_A_BOTTLE', 'AMBERGRIS']
    source_config.write_text(json.dumps(defaults))
    install(source, target, bot)
    installed = target / 'configs/bot-policy.json'
    config = json.loads(installed.read_text())
    assert config['potion_priority'] == defaults['potion_priority']
    config['potion_priority'] = ['ENERGY_POTION']
    installed.write_text(json.dumps(config))
    install(source, target, bot)
    assert json.loads(installed.read_text())['potion_priority'] == ['ENERGY_POTION']
