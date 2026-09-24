import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments/standalone-simulator'))
from replay_evidence import validate_replay, terminal


def case(name='native-replay-devoted_sculptor_cleanup.json'):
    source = json.loads((ROOT / 'experiments/standalone-simulator/fixtures' / name).read_text())
    native = source['nativeTrace']
    points = []
    plays = boundaries = completions = 0
    for event in native['events']:
        kind, value = event['kind'], event['value']
        if kind == 'play':
            point, stamp = f'before_play_{plays}', value['before']; plays += 1
        elif kind == 'action_completed':
            point, stamp = f'after_play_{plays - 1}', value['after']; completions += 1
        elif kind == 'end_turn':
            point, stamp = f'end_turn_{boundaries}', value['before']; boundaries += 1
        else:
            continue
        points.append(dict(point=point, expected=stamp, actual=stamp, matches=True))
    obs = native['result']['trainingObservation']
    result = dict(status='request_battle_completed', finalHp=obs['finalHp'], finalMaxHp=obs['finalMaxHp'], finishedTurn=native['result']['finishedTurn'],
        battle=dict(status='native_fixed_action_replay_matched', compared=points, plays=plays, boundaries=boundaries, completions=completions,
                    terminalActionWithoutPostStamp=False, terminalCleanupBoundaryComparisons=1))
    return native, result


def test_complete_states_and_terminal_validate():
    native, replay = case()
    assert validate_replay(native, replay)['checkpoints'] == 41


def test_complete_end_turn_only_battle_requires_each_full_state_and_terminal():
    native, replay = case('native-replay-end-turn-only-victory.json')
    assert replay['battle']['plays'] == 0
    assert validate_replay(native, replay)['checkpoints'] == 2
    replay['finalHp'] -= 1
    with pytest.raises(ValueError, match='Terminal or checkpoint mismatch'):
        validate_replay(native, replay)


def test_empty_action_trace_cannot_claim_a_complete_battle():
    native, replay = case('native-replay-end-turn-only-victory.json')
    native['events'] = native['events'][:1]
    replay['battle'].update(compared=[], boundaries=0)
    with pytest.raises(ValueError, match='No recorded combat action'):
        validate_replay(native, replay)


@pytest.mark.parametrize('mutation', ['missing_point', 'forged_matches', 'forged_expected', 'changed_turn', 'wrong_run', 'event_gap'])
def test_flags_cannot_hide_broken_native_evidence(mutation):
    native, replay = case()
    if mutation == 'missing_point': replay['battle']['compared'].pop()
    if mutation == 'forged_matches': replay['battle']['compared'][0]['actual'] += 'changed'
    if mutation == 'forged_expected':
        replay['battle']['compared'][0]['actual'] = replay['battle']['compared'][0]['expected'] = 'changed'
    if mutation == 'changed_turn': replay['finishedTurn'] += 1
    if mutation == 'wrong_run': native['result']['runId'] = 'wrong'
    if mutation == 'event_gap': native['events'][1]['sequence'] += 1
    with pytest.raises(ValueError): validate_replay(native, replay)


def test_duplicate_terminal_is_rejected(tmp_path):
    native, replay = case()
    log = tmp_path / 'replay.log'
    log.write_text((json.dumps(replay) + '\n') * 2)
    with pytest.raises(ValueError, match='exactly one terminal'): terminal(log)


def test_legacy_absent_summary_is_derived_from_terminal_and_events():
    native, replay = case()
    native.pop('complete')
    assert validate_replay(native, replay)['checkpoints'] == 41
    native['result']['combatEnded'] = False
    with pytest.raises(ValueError, match='Native terminal invalid'): validate_replay(native, replay)


def test_explicit_incomplete_capture_is_never_promoted():
    native, replay = case()
    native['complete'] = False
    with pytest.raises(ValueError, match='Native capture incomplete'): validate_replay(native, replay)


@pytest.mark.parametrize('mutation', ['wrong_count', 'early_boundary', 'missing_observation', 'ambiguous_boundary'])
def test_terminal_boundary_metadata_cannot_hide_an_earlier_difference(mutation):
    native, replay = case()
    battle = replay['battle']
    point = battle['compared'][-1]
    point.update(usedTerminalRewardBoundary=True, observedAfterRewards=point['actual'] + ';post-reward')
    battle['terminalRewardBoundaryComparisons'] = 1
    assert validate_replay(native, replay)['terminalRewardBoundaryComparisons'] == 1
    if mutation == 'wrong_count': battle['terminalRewardBoundaryComparisons'] = 2
    elif mutation == 'early_boundary':
        point['usedTerminalRewardBoundary'] = False
        battle['compared'][0].update(usedTerminalRewardBoundary=True, observedAfterRewards='later-state')
    elif mutation == 'missing_observation': point.pop('observedAfterRewards')
    else:
        point.update(usedTerminalCleanupBoundary=True, observedAfterCleanup='later-state')
    with pytest.raises(ValueError): validate_replay(native, replay)


@pytest.mark.parametrize('count', [-1, True, 1])
def test_terminal_choice_cancellation_cannot_be_claimed_after_a_play(count):
    native, replay = case()
    assert native['events'][-1]['kind'] == 'action_completed'
    replay['battle']['terminalBoundaryChoiceCancellations'] = count
    with pytest.raises(ValueError): validate_replay(native, replay)


def test_lethal_sly_turn_setup_may_cancel_a_later_recorded_setup_choice():
    native, replay = case('native-replay-terminal-sly-setup-cancelled.json')
    replay['battle']['terminalBoundaryChoiceCancellations'] = 1
    assert validate_replay(native, replay)['checkpoints'] == 56


@pytest.mark.parametrize('mutation', ['wrong_owner', 'excess_count', 'later_deployment', 'wrong_hp'])
def test_terminal_setup_cancellation_preserves_strict_plan_and_terminal_checks(mutation):
    native, replay = case('native-replay-terminal-sly-setup-cancelled.json')
    replay['battle']['terminalBoundaryChoiceCancellations'] = 1
    if mutation == 'wrong_owner':
        native['events'][-1]['value']['owner'] = 'turn_setup:6'
    elif mutation == 'excess_count':
        replay['battle']['terminalBoundaryChoiceCancellations'] = 3
    elif mutation == 'later_deployment':
        native['events'].append(dict(sequence=len(native['events']) + 1, kind='choice_plan',
                                     value=dict(owner='deployment:5:0:STRIKE_SILENT', choices=[])))
    else:
        replay['finalHp'] -= 1
    with pytest.raises(ValueError):
        validate_replay(native, replay)
