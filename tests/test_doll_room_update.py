from pathlib import Path

import pytest

from tools.install_doll_room_update import REPLACEMENTS, install


def test_install_preserves_other_policy_changes_and_is_idempotent(tmp_path):
    root = Path(__file__).resolve().parents[1]
    target = tmp_path / 'advisor-service'
    (target / 'runctl').mkdir(parents=True)
    policy = (root / 'runctl/policy.py').read_text()
    for old, new in reversed(REPLACEMENTS):
        policy = policy.replace(new, old)
    policy += '\nUSER_MARKER = 123\n'
    path = target / 'runctl/policy.py'
    path.write_text(policy)
    event = target / 'runctl/event_policy.py'
    event.write_text('# previous event policy\n')
    config = target / 'runtime.json'
    config.write_text('{"action_timeout_seconds": 1800}')
    backup = install(root, target)
    assert (backup / 'policy.py').read_text() == policy
    assert (backup / 'event_policy.py').read_text() == '# previous event policy\n'
    installed = path.read_text()
    expected = policy
    for old, new in REPLACEMENTS:
        expected = expected.replace(old, new, 1)
    assert installed == expected
    assert config.read_text() == '{"action_timeout_seconds": 1800}'
    install(root, target)
    assert path.read_text() == installed


def test_unknown_policy_stops_before_any_write(tmp_path):
    root = Path(__file__).resolve().parents[1]
    (tmp_path / 'runctl').mkdir()
    policy = tmp_path / 'runctl/policy.py'
    policy.write_text('# unknown version\n')
    event = tmp_path / 'runctl/event_policy.py'
    event.write_text('# unchanged\n')
    with pytest.raises(ValueError, match='Unrecognized'):
        install(root, tmp_path)
    assert policy.read_text() == '# unknown version\n'
    assert event.read_text() == '# unchanged\n'
    assert not (tmp_path / 'update-backups').exists()
