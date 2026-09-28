"""Shared validation of native fixed-action recordings against standalone replays.

Successful native captures cannot be replaced with a more convenient retry, and
summary flags never substitute for the recorded full-state checkpoints.
"""
import hashlib
import json
import os
from pathlib import Path
import uuid


def write(path, value):
    data = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()
    tmp = path.with_name(path.name + "." + uuid.uuid4().hex)
    with tmp.open("xb") as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    assert tmp.read_bytes() == data
    os.replace(tmp, path)
    assert path.read_bytes() == data


def require(value, message):
    if not value:
        raise ValueError(message)


def identity(path):
    path = Path(path)
    return dict(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())


def normalized(request):
    return {k: v for k, v in request.items() if k != 'runId'}


def terminal(log):
    values = []
    for line in Path(log).read_text().splitlines():
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            values.append(value)
    results = [v for v in values if v.get('status') == 'request_battle_completed']
    require(len(results) == 1, f'Expected exactly one terminal in {log}')
    require(not any(v.get('status') == 'native_replay_mismatch' for v in values), f'Mismatch in {log}')
    return results[0]


def matched(native, result):
    battle = result.get('battle', {})
    observation = native['result']['trainingObservation']
    points = battle.get('compared', [])
    hp = result.get('finalHp')
    return (result.get('status') == 'request_battle_completed'
            and battle.get('status') == 'native_fixed_action_replay_matched'
            and bool(points) and all(p.get('matches') is True for p in points)
            and type(hp) is int and hp == observation['finalHp']
            and result.get('finalMaxHp') == observation['finalMaxHp']
            and result.get('finishedTurn') == native['result']['finishedTurn']
            and (hp <= 0) == observation['playerDied']
            and observation['initialHp'] - hp == observation['netHpLoss'])


def validate_replay(native, result, *, require_terminal_state=True):
    # Early v1 recorders omitted this summary flag. Derive completeness from
    # the actual terminal and contiguous events below; explicit false still fails.
    require('complete' not in native or native['complete'] is True, 'Native capture incomplete')
    require(native['result']['status'] == 'Passed' and native['result']['combatEnded'] is True, 'Native terminal invalid')
    require(native['result']['runId'] == native['request']['runId'], 'Native run identity mismatch')
    events = native['events']
    require(bool(events) and events[0]['kind'] == 'initialized', 'Missing initialization')
    require([e['sequence'] for e in events] == list(range(1, len(events) + 1)), 'Incomplete event sequence')
    expected = []
    plays = boundaries = completions = 0
    pending = False
    planned_boundary_choices = last_boundary_choices = 0
    last_boundary_index = -1
    last_boundary_turn = None
    for index, event in enumerate(events):
        kind, value = event['kind'], event['value']
        if kind == 'play':
            require(not pending, 'Missing action completion')
            expected.append((f'before_play_{plays}', value['before']))
            plays += 1
            pending = True
        elif kind == 'action_completed':
            require(pending, 'Unexpected action completion')
            expected.append((f'after_play_{plays - 1}', value['after']))
            completions += 1
            pending = False
        elif kind == 'end_turn':
            require(not pending, 'Missing completion before end turn')
            expected.append((f'end_turn_{boundaries}', value['before']))
            boundaries += 1
            last_boundary_choices = planned_boundary_choices
            planned_boundary_choices = 0
            last_boundary_index = index
            turn_field = value['before'].split(';', 1)[0]
            require(turn_field.startswith('turn='), 'Missing boundary turn')
            last_boundary_turn = int(turn_field.removeprefix('turn='))
        else:
            require(kind in ('initialized', 'choice_plan'), f'Unexpected event {kind}')
            if kind == 'choice_plan' and value['owner'].startswith('deployment_end_turn:'):
                planned_boundary_choices = len(value['choices'])
    observation = native['result']['trainingObservation']
    opening_terminal = observation.get('openingTerminal', False)
    require(type(opening_terminal) is bool, 'Invalid native opening terminal marker')
    require(plays + boundaries > 0 or opening_terminal, 'No recorded combat action')
    require((plays + boundaries == 0) == opening_terminal
            and result.get('openingTerminal', False) is opening_terminal
            and result['battle'].get('openingTerminal', False) is opening_terminal,
            'Opening terminal boundary mismatch')
    terminal_state = observation.get('finalCombatState')
    has_terminal_state = isinstance(terminal_state, str) and bool(terminal_state.strip())
    require(not (require_terminal_state or opening_terminal) or has_terminal_state, 'Missing native complete terminal state')
    action_checkpoints = len(expected)
    if has_terminal_state:
        require(result.get('finalCombatState') == terminal_state, 'Complete terminal state mismatch')
        expected.append(('terminal', terminal_state))
    require(matched(native, result), 'Terminal or checkpoint mismatch')
    battle = result['battle']
    points = battle['compared']
    require(len(points) == len(expected), 'Missing or extra checkpoint')
    for point, (name, stamp) in zip(points, expected):
        require(point['point'] == name and point['expected'] == stamp and point['actual'] == stamp,
                f'Full native state mismatch: {name}')
    # Boundary observations remain whole states and may only identify the last
    # recorded action completion. They cannot excuse an earlier discrepancy.
    for flag, counter, observed in (
            ('usedTerminalCleanupBoundary', 'terminalCleanupBoundaryComparisons', 'observedAfterCleanup'),
            ('usedTerminalRewardBoundary', 'terminalRewardBoundaryComparisons', 'observedAfterRewards')):
        uses = [point for point in points if point.get(flag) is True]
        if any(flag in point for point in points) or counter == 'terminalRewardBoundaryComparisons':
            require(battle.get(counter, 0) == len(uses), 'Terminal boundary count mismatch')
        for point in uses:
            require(point is points[action_checkpoints - 1] and events[-1]['kind'] == 'action_completed',
                    'Terminal boundary used before final completion')
            require(isinstance(point.get(observed), str) and point[observed] != point['actual'],
                    'Missing distinct post-boundary observation')
            require(not (point.get('usedTerminalCleanupBoundary') and point.get('usedTerminalRewardBoundary')),
                    'Ambiguous terminal boundary')
    require((battle['plays'], battle['boundaries'], battle['completions']) == (plays, boundaries, completions), 'Action count mismatch')
    require(battle['terminalActionWithoutPostStamp'] == pending, 'Terminal completion metadata mismatch')
    cancelled = battle.get('terminalBoundaryChoiceCancellations', 0)
    require(type(cancelled) is int and cancelled >= 0, 'Invalid cancelled terminal choice count')
    if cancelled:
        trailing = events[last_boundary_index + 1:]
        require(last_boundary_index >= 0 and all(
            e['kind'] == 'choice_plan' and e['value']['owner'] == f'turn_setup:{last_boundary_turn + 1}'
            for e in trailing),
                'Cancelled choice does not belong to the final recorded boundary')
        setup_choices = sum(len(e['value']['choices']) for e in trailing)
        require(cancelled <= last_boundary_choices + setup_choices,
                'Cancelled choice count exceeds the recorded terminal boundary plan')
    return dict(plays=plays, checkpoints=action_checkpoints, openingTerminal=opening_terminal, terminalCheckpoints=int(has_terminal_state),
                terminalStateVerified=has_terminal_state, finalHp=result['finalHp'], finishedTurn=result['finishedTurn'],
                terminalCleanupBoundaryComparisons=battle['terminalCleanupBoundaryComparisons'],
                terminalRewardBoundaryComparisons=battle.get('terminalRewardBoundaryComparisons', 0),
                terminalBoundaryChoiceCancellations=cancelled)
