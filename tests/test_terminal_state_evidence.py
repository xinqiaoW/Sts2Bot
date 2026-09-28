import pytest

from test_native_target_artifacts import case
from replay_evidence import validate_replay


def terminal_case():
    native, replay = case()
    # Synthetic terminal fixture, separate from immutable historical recordings.
    stamp = 'turn=4;hp=67;E0=7/STABBOT/bot3/22/22/0/STAB;R=1:2:3:4:5'
    native['result']['trainingObservation']['finalCombatState'] = stamp
    replay['finalCombatState'] = stamp
    replay['battle']['compared'].append(dict(point='terminal', expected=stamp, actual=stamp, matches=True))
    return native, replay


def test_missing_terminal_state_cannot_certify_full_battle():
    native, replay = case()
    with pytest.raises(ValueError, match='terminal state'):
        validate_replay(native, replay)


def test_terminal_checkpoint_is_verified_but_not_counted_as_an_action():
    native, replay = terminal_case()
    report = validate_replay(native, replay)
    assert report['checkpoints'] == 41
    assert report['terminalCheckpoints'] == 1
    assert report['terminalStateVerified'] is True


@pytest.mark.parametrize('mutation', ['native_missing', 'empty', 'wrong_roster', 'missing_point',
                                     'forged_matches', 'forged_expected', 'wrong_top_level', 'boundary_fallback'])
def test_terminal_hp_cannot_mask_wrong_or_missing_complete_state(mutation):
    native, replay = terminal_case()
    point = replay['battle']['compared'][-1]
    if mutation == 'native_missing': native['result']['trainingObservation'].pop('finalCombatState')
    elif mutation == 'empty': native['result']['trainingObservation']['finalCombatState'] = ''
    elif mutation == 'wrong_roster': native['result']['trainingObservation']['finalCombatState'] += ';E1=extra'
    elif mutation == 'missing_point': replay['battle']['compared'].pop()
    elif mutation == 'forged_matches': point['actual'] += ';R=wrong'
    elif mutation == 'forged_expected': point['expected'] = point['actual'] = 'invented'
    elif mutation == 'wrong_top_level': replay['finalCombatState'] += ';wrong'
    else:
        point.update(usedTerminalRewardBoundary=True, observedAfterRewards='other state')
        replay['battle']['terminalRewardBoundaryComparisons'] = 1
    with pytest.raises(ValueError):
        validate_replay(native, replay)


def test_legacy_audit_is_explicit_and_never_claims_terminal_state():
    native, replay = case()
    report = validate_replay(native, replay, require_terminal_state=False)
    assert report['terminalCheckpoints'] == 0
    assert report['terminalStateVerified'] is False
