"""Automatic continuation must respect actual process ownership and drain."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

import psutil
import pytest

path = Path(__file__).resolve().parents[1] / 'experiments/standalone-simulator/advance_acceptance.py'
spec = importlib.util.spec_from_file_location('advance_acceptance', path)
advance = importlib.util.module_from_spec(spec); spec.loader.exec_module(advance)


def test_live_validation_is_not_considered_drained():
    owner = psutil.Process()
    assert advance.owner_alive(owner.pid, owner.create_time())
    with pytest.raises(ValueError, match='PID was reused'):
        advance.owner_alive(owner.pid, owner.create_time() - 1)


def test_finished_process_is_terminal_not_a_reason_to_restart():
    child = subprocess.Popen([sys.executable, '-c', 'pass'])
    created = psutil.Process(child.pid).create_time()
    child.wait(timeout=5)
    assert not advance.owner_alive(child.pid, created)


def test_observation_error_does_not_mean_terminal(monkeypatch):
    def denied(pid): raise psutil.AccessDenied(pid)
    monkeypatch.setattr(advance.psutil, 'Process', denied)
    with pytest.raises(psutil.AccessDenied):
        advance.owner_alive(os.getpid(), 0)


def summary():
    return dict(requestedComparisonPassed=True, workerExitCodes=[0] * 16,
                validatedBuildCount=10016, validatedTargetCount=80, totalCheckpoints=510000,
                unresolvedReplayDifferences=0, complete=False)


def test_threshold_drain_does_not_require_executing_every_reserve_input():
    advance.require_drained_summary(summary())


@pytest.mark.parametrize('key,value', [
    ('requestedComparisonPassed', False), ('workerExitCodes', [0, None]),
    ('workerExitCodes', []), ('workerExitCodes', [0, 1]), ('validatedBuildCount', 9999),
    ('validatedTargetCount', 79), ('totalCheckpoints', 499999), ('unresolvedReplayDifferences', 1),
])
def test_partial_or_failed_validation_never_advances(key, value):
    report = summary(); report[key] = value
    with pytest.raises(ValueError): advance.require_drained_summary(report)


def write(path, value):
    path.write_text(json.dumps(value))


def test_failed_stage_retains_exit_and_refuses_silent_retry(tmp_path, monkeypatch):
    sleep = advance.time.sleep
    monkeypatch.setattr(advance.time, 'sleep', lambda seconds: sleep(.01))
    command = [sys.executable, '-c', 'import sys;print("original failure");sys.exit(7)']
    with pytest.raises(RuntimeError, match='exit code 7'):
        advance.execute_stage('unit', command, tmp_path, write, lambda cmd: cmd)
    assert json.loads((tmp_path / 'unit-exit.json').read_text())['exitCode'] == 7
    original = (tmp_path / 'unit.log').read_bytes()
    with pytest.raises(FileExistsError):
        advance.execute_stage('unit', command, tmp_path, write, lambda cmd: cmd)
    assert (tmp_path / 'unit.log').read_bytes() == original


def test_stop_marker_prevents_next_stage_start(tmp_path):
    (tmp_path / 'STOP').touch()
    with pytest.raises(RuntimeError, match='stop marker'):
        advance.execute_stage('unit', ['/does/not/exist'], tmp_path, write, lambda cmd: cmd)
    assert not (tmp_path / 'unit.log').exists()
