import json
import pytest

from runctl.audit import audit_episode


def write(path, value):
    path.write_text(json.dumps(value))


@pytest.fixture
def recorded_game(tmp_path):
    native, policy = tmp_path / 'native', tmp_path / 'policy'
    native.mkdir(); policy.mkdir()
    config = dict(normal_card_min_gain=1, crisis_card_min_gain=0)
    result = dict(runId='game', status='complete', outcome='death', state=dict(hp=0), decisionCount=1)
    write(native / 'result.json', result)
    write(native / 'accepted.json', dict(runId='game', seed='seed', characterId='SILENT',
        ascension=10, combatMode='solver', decisionMode='all'))
    events = [dict(runId='game', kind='run_started', payload=dict(state=dict(hp=56, maxHp=70),
        details=dict(fullContentDiscovery=True))), dict(runId='game', kind='decision', payload=dict(
        decisionSeq=1, screen='CARD_REWARD', options=[dict(kind='card', action='take'), dict(kind='skip')])),
        dict(runId='game', kind='action', payload=dict(details=dict(decisionSeq=1, choice=0)))]
    (native / 'events.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    write(policy / 'policy-config.json', config)
    row = dict(runId='game', seed='seed', screen='CARD_REWARD', decisionSeq=1, choice=0,
        config=config, warnings=[], elapsed_seconds=.5, rollout_depth=0, crisis=False,
        scores={'0': -18.99, '1': -20}, skip_score=-20, keep_per_parent=4, stats=dict(per_depth=[]))
    write(policy / 'decisions.jsonl', row)
    return dict(result, seed='seed', artifactDirectory=str(native)), policy, row


def test_audit_matches_real_actions_and_strict_margin(recorded_game):
    episode, policy, _ = recorded_game
    result = audit_episode(episode, policy)
    assert result['checked_decisions'] == result['threshold_card_takes'] == 1


@pytest.mark.parametrize('change', ['equality', 'action', 'config', 'missing'])
def test_audit_rejects_recorded_inconsistencies(recorded_game, change):
    episode, policy, row = recorded_game
    if change == 'equality': row['scores']['0'] = -19
    elif change == 'action': row['choice'] = 1
    elif change == 'config': row['config']['normal_card_min_gain'] = 0
    if change == 'missing': (policy / 'decisions.jsonl').write_text('')
    else: write(policy / 'decisions.jsonl', row)
    with pytest.raises(ValueError): audit_episode(episode, policy)
