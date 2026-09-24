"""The build gate must count unique verified states, not summaries or retries."""
import json
from pathlib import Path
import sqlite3

import pytest
from test_native_target_artifacts import case, ROOT
import audit_build_panel
from replay_evidence import identity


@pytest.fixture(autouse=True)
def frozen_panel(monkeypatch):
    # Full panel validation needs the 10000-build catalog plan; covered separately.
    monkeypatch.setattr(audit_build_panel, 'validate_build_panel', lambda plan, root: dict(passed=True))


def panel(tmp_path):
    native, replay = case()
    host = tmp_path / 'host.dll'
    host.write_bytes(b'auditor-test-host')
    case_dir = tmp_path / 'cases/000-unit'
    case_dir.mkdir(parents=True)
    native['directory'] = str(case_dir / 'native-source')
    Path(native['directory']).mkdir()
    (Path(native['directory']) / 'trace.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in native['events']))
    raw = case_dir / 'native.json'
    raw.write_text(json.dumps(native))
    fixture = case_dir / 'fixture.json'
    fixture.write_text(json.dumps(dict(nativeTrace=native, request=native['request'])))
    log = case_dir / 'replay.log'
    log.write_text(json.dumps(replay) + '\n')
    entry = dict(caseId='unit', caseIndex=0, hostSha256=identity(host)['sha256'], passed=True,
                 captureAttempts=[dict(attempt=1, recording=identity(raw), complete=True)],
                 replayExecution=dict(exitCode=0, timedOut=False), replayCommand=['dotnet', str(host)],
                 fixture=identity(fixture), replayLog=identity(log), plays=replay['battle']['plays'], checkpoints=41)
    result = case_dir / 'result.json'
    result.write_text(json.dumps(entry))
    db_path = tmp_path / 'cases.sqlite'
    with sqlite3.connect(db_path) as db:
        db.execute('CREATE TABLE cases(case_index INTEGER,case_id TEXT,body TEXT)')
        db.execute('INSERT INTO cases VALUES(?,?,?)', (0, 'unit', json.dumps(dict(
            request=native['request'], sourceBuildId='build', target='target'))))
    plan = tmp_path / 'plan.json'
    plan.write_text(json.dumps(dict(caseDatabase=str(db_path), caseDatabaseSha256=identity(db_path)['sha256'],
                                   requiredValidatedBuilds=10000, caseCount=1, buildCount=1, targetCount=80,
                                   priorActuallyPlayedCards=[], teacher=native['teacher'])))
    return host, plan, result


def audit(tmp_path, host, plan, target=41):
    return audit_build_panel.audit(ROOT, tmp_path, plan, host, target)


def test_only_individually_verified_checkpoints_count(tmp_path):
    host, plan, _ = panel(tmp_path)
    report = audit(tmp_path, host, plan)
    assert report['matchedCheckpoints'] == 41
    assert report['matchedBattles'] == 1
    assert report['uniqueBuilds'] == 1
    assert report['unresolvedReplayDifferences'] == [] and report['staleHostResults'] == []


def test_one_verified_build_cannot_pass_the_ten_thousand_build_gate(tmp_path):
    host, plan, _ = panel(tmp_path)
    report = audit(tmp_path, host, plan, target=0)
    assert report['matchedCheckpoints'] == 41
    assert report['passed'] is False


def test_result_from_another_host_is_stale_not_counted(tmp_path):
    host, plan, _ = panel(tmp_path)
    other = tmp_path / 'other.dll'
    other.write_bytes(b'another-host')
    report = audit(tmp_path, other, plan)
    assert report['matchedCheckpoints'] == 0
    assert len(report['staleHostResults']) == 1


@pytest.mark.parametrize('mutation', ['inflated_summary', 'duplicate_case', 'changed_raw', 'changed_host', 'recaptured_success', 'changed_emitted_trace'])
def test_evidence_cannot_be_inflated_or_replaced(tmp_path, mutation):
    host, plan, result = panel(tmp_path)
    entry = json.loads(result.read_text())
    if mutation == 'inflated_summary':
        entry['checkpoints'] = 500000
    elif mutation == 'duplicate_case':
        duplicate = tmp_path / 'cases/001-duplicate'
        duplicate.mkdir()
        (duplicate / 'result.json').write_text(json.dumps(entry))
    elif mutation == 'changed_raw':
        raw = Path(entry['captureAttempts'][0]['recording']['path'])
        raw.write_text(raw.read_text() + ' ')
    elif mutation == 'changed_host':
        other = tmp_path / 'other.dll'
        other.write_bytes(b'another-host')
        entry['replayCommand'][1] = str(other)
    elif mutation == 'recaptured_success':
        entry['captureAttempts'].append({**entry['captureAttempts'][0], 'attempt': 2})
    elif mutation == 'changed_emitted_trace':
        trace = result.parent / 'native-source/trace.jsonl'
        trace.write_text(trace.read_text().replace('"sequence": 1,', '"sequence": 999,', 1))
    result.write_text(json.dumps(entry))
    with pytest.raises(ValueError):
        audit(tmp_path, host, plan)
