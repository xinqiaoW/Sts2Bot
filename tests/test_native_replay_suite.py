import copy
import importlib.util
from pathlib import Path
import sys

import pytest

source = Path(__file__).resolve().parents[1] / 'experiments/standalone-simulator'
sys.path.insert(0, str(source))
spec = importlib.util.spec_from_file_location('native_replay_suite', source / 'run_native_replay_suite.py')
suite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(suite)
sys.path.remove(str(source))


def observations():
    native = dict(result=dict(finishedTurn=5, trainingObservation=dict(initialHp=70, finalHp=42,
                  finalMaxHp=70, netHpLoss=28, playerDied=False)))
    replay = dict(status='request_battle_completed', historicalTerminalMatched=None, finalHp=42,
                  finalMaxHp=70, finishedTurn=5, battle=dict(status='native_fixed_action_replay_matched',
                  compared=[dict(matches=True)]))
    return native, replay


def test_replay_mode_uses_actual_native_terminal_when_historical_flag_is_null():
    native, replay = observations()
    assert suite.matched(native, replay)


@pytest.mark.parametrize('field,value', [('finalHp', 41), ('finalMaxHp', 69), ('finishedTurn', 4)])
def test_matching_checkpoints_cannot_hide_wrong_terminal(field, value):
    native, replay = observations()
    replay[field] = value
    assert not suite.matched(native, replay)


@pytest.mark.parametrize('points', [[], [dict(matches=False)], [dict(matches=True), dict(matches=False)]])
def test_matching_terminal_cannot_hide_missing_or_wrong_checkpoints(points):
    native, replay = observations()
    replay['battle']['compared'] = copy.deepcopy(points)
    assert not suite.matched(native, replay)
