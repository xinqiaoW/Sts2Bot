import importlib
import json
from pathlib import Path
import sys
import types

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
panel = importlib.import_module('run_standalone_failure_panel')


def setup_case(tmp_path, monkeypatch, completed):
    campaign, output, bundle = (tmp_path / name for name in ('campaign', 'output', 'bundle'))
    for path in (campaign, output, bundle): path.mkdir()
    host = tmp_path / 'host.dll'; host.write_bytes(b'test host')
    progress = bundle / 'progress-snapshot.json'; progress.write_text('{}')
    (bundle / 'runtime-template.json').write_text(json.dumps(dict(dotnet='dotnet', game_dir='game')))
    plan = dict(nativeSource=str(tmp_path / 'source'), bundle=str(bundle), traceDll=dict(sha256='trace'))
    (campaign / 'plan.json').write_text(json.dumps(plan))
    entries = []
    for index, successes in enumerate(completed, 1):
        old = campaign / 'quarantine-audit' / f'case-{index:06}'
        old.mkdir(parents=True)
        entry = dict(job=f'job-{index}', build=f'build-{index}', target='target', dataset='real', request=dict(runId='original', seed='same'))
        entries.append((index, entry))
        (old / 'request.json').write_text(json.dumps(dict(sourceJobId=entry['job'])))
        for attempt, success in enumerate(successes, 1):
            request = dict(entry['request'], runId=f'capture-{index}-{attempt}')
            events = [dict(sequence=1, kind='initialized', value={})]
            native = dict(request=request, complete=success, progressSnapshotSha256=panel.identity(progress)['sha256'], traceModSha256='trace', directory=str(old), events=events)
            (old / f'native-{attempt}.json').write_text(json.dumps(native))
            (old / (request['runId']+'.jsonl')).write_text(json.dumps(events[0])+'\n')
    def unexpected_capture(*args, **kwargs): raise AssertionError('Historical attempts must not be replaced')
    monkeypatch.setitem(sys.modules, 'persistent_capture_v2', types.SimpleNamespace(PersistentCapture=unexpected_capture))
    monkeypatch.setattr(panel, 'replay_fixture', lambda native, job, build: dict(native=native))
    return campaign, output, host, entries


def test_original_success_is_replayed_once_and_failure_does_not_skip_later_cases(tmp_path, monkeypatch):
    campaign, output, host, entries = setup_case(tmp_path, monkeypatch, [[True], [True]])
    calls = []
    def execute(command, **kwargs):
        calls.append(command); kwargs['stdout'].write('original replay failure\n')
        return types.SimpleNamespace(returncode=1)
    monkeypatch.setattr(panel.subprocess, 'run', execute)
    panel.diagnose_group(0, entries, campaign, output, host)
    assert len(calls) == 2
    for index in (1, 2):
        receipt = json.loads((output / f'case-{index:06}/result.json').read_text())
        assert receipt['status'] == 'mismatch'
        assert len(receipt['nativeAttempts']) == 1
        assert Path(receipt['nativeAttempts'][0]['path']).is_relative_to(campaign)
    assert panel.summarize(output, 2)['passed'] is False


def test_three_historical_native_failures_stay_failed(tmp_path, monkeypatch):
    campaign, output, host, entries = setup_case(tmp_path, monkeypatch, [[False, False, False]])
    panel.diagnose_group(0, entries, campaign, output, host)
    receipt = json.loads((output / 'case-000001/result.json').read_text())
    assert receipt['status'] == 'native_failed'
    assert len(receipt['nativeAttempts']) == 3
    assert panel.summarize(output, 1)['passed'] is False


def test_changed_request_is_an_error_not_a_capture_retry(tmp_path, monkeypatch):
    campaign, output, host, entries = setup_case(tmp_path, monkeypatch, [[True]])
    entries[0][1]['request']['seed'] = 'different'
    panel.diagnose_group(0, entries, campaign, output, host)
    receipt = json.loads((output / 'case-000001/result.json').read_text())
    assert receipt['status'] == 'error'
    assert 'changed the requested input' in receipt['error']


def test_raw_trace_tampering_is_rejected(tmp_path, monkeypatch):
    campaign, output, host, entries = setup_case(tmp_path, monkeypatch, [[True]])
    raw = next((campaign / 'quarantine-audit').glob('*/native-1.json'))
    native = json.loads(raw.read_text())
    (Path(native['directory']) / (native['request']['runId'] + '.jsonl')).write_text('{}\n')
    panel.diagnose_group(0, entries, campaign, output, host)
    receipt = json.loads((output / 'case-000001/result.json').read_text())
    assert receipt['status'] == 'error'
    assert 'Raw native trace differs' in receipt['error']
