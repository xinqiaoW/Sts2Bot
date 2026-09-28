import importlib
import json
from pathlib import Path
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/standalone-simulator'))
replay = importlib.import_module('replay_build_panel')


def fixture(tmp_path, complete=True):
    original = tmp_path / 'old' / 'case-001'
    original.mkdir(parents=True)
    host = tmp_path / 'host.dll'; host.write_bytes(b'new host')
    native = dict(complete=complete, request=dict(runId='original'))
    raw = original / 'native.json'; raw.write_text(json.dumps(native))
    request = original / 'fixture.json'; request.write_text(json.dumps(dict(nativeTrace=native, request=native['request'])))
    result = original / 'result.json'
    result.write_text(json.dumps(dict(caseIndex=1, caseId='case', target='target', act='HIVE', seed='seed',
        sourceBuildId='build', captureAttempts=[dict(attempt=1, recording=replay.identity(raw))],
        fixture=replay.identity(request), passed=True, checkpoints=999, plays=888, hostSha256='OLD')))
    return result, raw, host, tmp_path / 'new'


def test_old_counts_are_not_inherited_on_native_failure(tmp_path):
    source, raw, host, destination = fixture(tmp_path, complete=False)
    before = replay.identity(source)
    result = replay.replay_case(source, destination, host, {}, tmp_path / 'progress')
    assert result['passed'] is False
    assert result['failureStage'] == 'native_capture'
    assert 'checkpoints' not in result and 'plays' not in result
    assert replay.identity(source) == before


def test_changed_successful_capture_cannot_be_replayed(tmp_path):
    source, raw, host, destination = fixture(tmp_path)
    raw.write_text('{}')
    result = replay.replay_case(source, destination, host, {}, tmp_path / 'progress')
    assert result['passed'] is False
    assert result['failureStage'] == 'evidence'
    assert 'Original recording changed' in result['error']


def test_new_replay_failure_is_not_old_host_success(tmp_path, monkeypatch):
    source, raw, host, destination = fixture(tmp_path)
    def execute(command, **kwargs):
        assert kwargs['timeout'] == 120
        kwargs['stdout'].write('replay failed')
        return types.SimpleNamespace(returncode=1)
    monkeypatch.setattr(replay.subprocess, 'run', execute)
    result = replay.replay_case(source, destination, host, dict(dotnet='dotnet', game_dir='game'), tmp_path / 'progress')
    assert result['passed'] is False
    assert result['failureStage'] == 'standalone_replay'
    assert 'checkpoints' not in result
    assert result['hostSha256'] == replay.identity(host)['sha256']
    assert result['replayCommand'][1] == str(host)
