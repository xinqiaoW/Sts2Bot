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


@pytest.mark.parametrize('forged_state', [False, True])
def test_suite_uses_strict_evidence_and_counts_terminal_separately(tmp_path, monkeypatch, forged_state):
    import json
    from types import SimpleNamespace
    from test_terminal_state_evidence import terminal_case

    native, replay = terminal_case()
    if forged_state:
        replay['battle']['compared'][-1]['actual'] += ';forged-roster'
    fixtures = tmp_path / 'fixtures'
    fixtures.mkdir()
    (fixtures / 'native-replay-terminal.json').write_text(json.dumps(dict(nativeTrace=native)))
    host, progress = tmp_path / 'host.dll', tmp_path / 'progress.json'
    host.write_bytes(b'test host')
    progress.write_text('{}')
    report = tmp_path / 'report.json'
    monkeypatch.setattr(sys, 'argv', ['suite', '--host-dll', str(host), '--runtime', str(tmp_path),
        '--progress-snapshot', str(progress), '--report', str(report), '--dotnet', 'test-dotnet',
        '--fixtures', str(fixtures)])

    def execute(command, **kwargs):
        assert kwargs['timeout'] == 120
        kwargs['stdout'].write(json.dumps(replay) + '\n')
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(suite.subprocess, 'run', execute)
    if forged_state:
        with pytest.raises(SystemExit):
            suite.main()
    else:
        suite.main()
    result = json.loads(report.read_text())
    assert result['passed'] is (not forged_state)
    if not forged_state:
        assert result['totalCheckpoints'] == 41
        assert result['totalTerminalCheckpoints'] == 1
