import json
from pathlib import Path

import pytest

from tools.install_adaptive_weights_update import CONFIG_FILES, SOURCE_FILES, install


def test_preserves_all_user_values_and_timeout_files(tmp_path):
    source = Path(__file__).resolve().parents[1]
    target = tmp_path / 'advisor-service'
    for name in SOURCE_FILES:
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# previous source\n')
    custom = dict(short_weight=.3, long_weight=.7, samples_per_parent=32, keep_per_parent=6,
                  leaf_top_weight=.8, leaf_bottom_weight=.2, weak_short_weight=.9,
                  weak_long_weight=.1, short_strength_loss_threshold=12)
    for name in CONFIG_FILES:
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(custom))
    (target / 'runctl/env.py').write_text('# timeout fix')
    (target / 'runtime.json').write_text('{"action_timeout_seconds": 1800}')
    backup = install(source, target)
    for name in SOURCE_FILES:
        assert (target / name).read_bytes() == (source / name).read_bytes()
        assert (backup / name).read_text() == '# previous source\n'
    for name in CONFIG_FILES:
        updated = json.loads((target / name).read_text())
        assert all(updated[k] == v for k, v in custom.items())
        assert 'lookahead_pairs' in updated
        assert json.loads((backup / name).read_text()) == custom
    assert (target / 'runctl/env.py').read_text() == '# timeout fix'
    assert (target / 'runtime.json').read_text() == '{"action_timeout_seconds": 1800}'


def test_missing_input_fails_without_writes(tmp_path):
    source = Path(__file__).resolve().parents[1]
    with pytest.raises(FileNotFoundError):
        install(source, tmp_path)
    assert not list(tmp_path.iterdir())
