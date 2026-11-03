import json
from pathlib import Path

import pytest

from tools.install_card_search_update import install, SOURCE_FILES, CONFIG_KEYS


def test_update_preserves_settings_and_backs_up(tmp_path):
    source = Path(__file__).resolve().parents[1]
    target = tmp_path / 'advisor-service'
    for name in SOURCE_FILES:
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text('# installed version\n')
    for name in CONFIG_KEYS:
        dest = target / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(dict(short_weight=.31, long_weight=.69,
            reward_rollout_depth=5, normal_card_min_gain=1.5, keep_per_parent=4,
            samples_per_parent=40, crisis_samples_per_parent=100, lookahead_pairs=0,
            leaf_top_weight=.8, leaf_bottom_weight=.2)))
    backup = install(source, target)
    for name in SOURCE_FILES:
        assert (target / name).read_bytes() == (source / name).read_bytes()
        assert (backup / name).read_text() == '# installed version\n'
    for name, keys in CONFIG_KEYS.items():
        config = json.loads((target / name).read_text())
        assert config['short_weight'] == .31 and config['long_weight'] == .69
        assert config['reward_rollout_depth'] == 5 and config['normal_card_min_gain'] == 1.5
        assert config['keep_per_parent'] == 4 and config['samples_per_parent'] == 40
        assert config['crisis_samples_per_parent'] == 100 and config['lookahead_pairs'] == 0
        defaults = json.loads((source / name).read_text())
        assert all(config[k] == defaults[k] for k in keys)
        assert json.loads((backup / name).read_text())['keep_per_parent'] == 4


def test_incomplete_target_fails_before_changes(tmp_path):
    source = Path(__file__).resolve().parents[1]
    target = tmp_path / 'incomplete'
    target.mkdir()
    with pytest.raises(FileNotFoundError):
        install(source, target)
    assert not list(target.iterdir())
