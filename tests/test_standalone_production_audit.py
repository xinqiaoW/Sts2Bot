"""Synthetic production bindings and stopped-audit cases, without game processes."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import standalone_production_audit as production
import standalone_rollout_audit as audit
from standalone_rollout_metrics import identity, read, write


@pytest.fixture
def context(tmp_path, monkeypatch):
    handoff, rollout, bundle = (tmp_path / name for name in ('handoff', 'rollout', 'bundle'))
    teacher = dict(execution_backend='standalone-managed-native', unitFixture=True)
    write(bundle / 'teacher.json', teacher); write(bundle / 'release.json', {'fixture': True})
    native = dict(bundle=str(bundle), releaseManifest=identity(bundle / 'release.json'),
                  nativeSource=str(tmp_path / 'source'), nativeFiles={}, traceDll={'path': 'fixture', 'sha256': 'fixture'})
    write(rollout / 'plan.json', native)
    ready = dict(passed=True, releaseManifest=native['releaseManifest'], selectedWorkers=8)
    write(handoff / 'readiness.json', ready)
    instance = handoff / 'instance'
    write(instance / 'preparation.json', dict(directory=str(instance)))
    reports, queues = {}, {}
    for name in ('real', 'mutation', 'targeted'):
        path = handoff / (name + '.sqlite')
        report = dict(acceptance=identity(handoff / 'readiness.json'), sourceDatabase='native-' + name)
        with sqlite3.connect(path) as db:
            db.executescript('CREATE TABLE collection_settings(key TEXT PRIMARY KEY,value TEXT);'
                             'CREATE TABLE jobs(id TEXT PRIMARY KEY,build_id TEXT,target TEXT,teacher TEXT);'
                             'CREATE TABLE attempts(id INTEGER PRIMARY KEY,job_id TEXT,status TEXT,result TEXT);')
            db.execute('INSERT INTO collection_settings VALUES(?,?)', ('standalone_handoff', json.dumps(report)))
            db.execute('INSERT INTO jobs VALUES(?,?,?,?)', ('pending', 'build', '{"id":"target"}', json.dumps(teacher)))
        queues[name] = identity(path); reports[name] = report
    write(handoff / 'preparation.json', dict(prepared=True, instance=identity(instance / 'preparation.json'),
          readiness=identity(handoff / 'readiness.json'), releaseManifest=native['releaseManifest'], queues=queues, reports=reports))
    # Correctness/soak verification has its own raw-file integration tests. Here
    # it is an already-accepted prerequisite, not a real acceptance claim.
    monkeypatch.setattr('verify_standalone_acceptance.verify_acceptance', lambda folder: ready)
    monkeypatch.setattr('run_standalone_rollout.verify_plan', lambda folder: native)
    directory = tmp_path / 'audit'
    command = production.prepare(handoff, rollout, directory)
    spec = importlib.util.spec_from_file_location('frozen_production_audit_test', directory / 'control/standalone_production_audit.py')
    frozen = importlib.util.module_from_spec(spec); spec.loader.exec_module(frozen)
    return handoff, directory, frozen, command, native, teacher


def test_audits_mutable_new_queues_without_altering_readiness(context):
    handoff, directory, frozen, command, native, teacher = context
    before = (handoff / 'readiness.json').read_bytes()
    # Real collection changes the database hash; its migration/teacher binding
    # stays immutable and must still authorize auditing fresh completions.
    with sqlite3.connect(handoff / 'real.sqlite') as db:
        db.execute('INSERT INTO attempts VALUES(1,?,?,?)',
                   ('pending', 'complete', json.dumps({'collectionRequest': {'runId': 'fresh'}})))
    plan, paths, expected = frozen.load_context(directory)
    assert plan == native and expected == teacher and set(paths) == {'real', 'mutation', 'targeted'}
    assert command[-1] == '--production'
    assert (handoff / 'readiness.json').read_bytes() == before
    assert not (directory / 'audit-ready.json').exists()
    assert not (directory / 'native-audit').exists()


@pytest.mark.parametrize('change', ['readiness', 'code', 'teacher', 'migration', 'queue_path', 'instance', 'acceptance'])
def test_changed_production_bindings_fail_before_native_start(context, change, monkeypatch):
    handoff, directory, frozen, _, native, teacher = context
    if change == 'readiness': write(handoff / 'readiness.json', {'passed': False})
    elif change == 'code': (directory / 'control/standalone_rollout_audit.py').write_text('changed')
    elif change in ('teacher', 'migration'):
        with sqlite3.connect(handoff / 'real.sqlite') as db:
            if change == 'teacher': db.execute("UPDATE jobs SET teacher='{}'")
            else: db.execute("UPDATE collection_settings SET value='{}'")
    elif change == 'queue_path':
        p = directory / 'plan.json'; value = read(p); value['queues']['real'] = value['queues']['targeted']; write(p, value)
    elif change == 'instance': write(handoff / 'instance/preparation.json', {'changed': True})
    elif change == 'acceptance': monkeypatch.setattr('verify_standalone_acceptance.verify_acceptance', lambda p: {'passed': False})
    with pytest.raises(ValueError): frozen.load_context(directory)
    assert not (directory / 'native-audit').exists()


def test_changed_teacher_completion_does_not_advance_sampling_cursor(tmp_path):
    index = sqlite3.connect(':memory:')
    index.executescript('CREATE TABLE cursors(name TEXT PRIMARY KEY,value INTEGER);'
        'CREATE TABLE builds(id TEXT PRIMARY KEY,dataset TEXT,job TEXT,target TEXT,request TEXT);'
        'CREATE TABLE targets(id TEXT PRIMARY KEY);'
        'CREATE TABLE cases(id INTEGER PRIMARY KEY,dataset TEXT,job TEXT,build TEXT,target TEXT,request TEXT,status TEXT,UNIQUE(dataset,job));')
    path = tmp_path / 'queue.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript('CREATE TABLE jobs(id TEXT,build_id TEXT,target TEXT,teacher TEXT);'
                         'CREATE TABLE attempts(id INTEGER,job_id TEXT,status TEXT,result TEXT);')
        for i, teacher in enumerate(({'accepted': True}, {'accepted': False})):
            db.execute('INSERT INTO jobs VALUES(?,?,?,?)', (str(i), str(i), '{"id":"target"}', json.dumps(teacher)))
            db.execute('INSERT INTO attempts VALUES(?,?,?,?)', (i+1, str(i), 'complete', '{"collectionRequest":{}}'))
    with pytest.raises(ValueError, match='another teacher'): audit.ingest(index, {'real': path}, {'accepted': True})
    assert index.execute('SELECT count(*) FROM cursors').fetchone()[0] == 0
    assert index.execute('SELECT count(*) FROM builds').fetchone()[0] == 0


def test_exhausted_native_sample_stops_formal_audit_and_preserves_attempts(context, monkeypatch):
    handoff, directory, _, _, plan, teacher = context
    paths = {name: handoff / (name + '.sqlite') for name in ('real', 'mutation', 'targeted')}
    with sqlite3.connect(paths['real']) as db:
        db.execute('INSERT INTO attempts VALUES(1,?,?,?)', ('pending', 'complete', '{"collectionRequest":{"runId":"sample"}}'))
    monkeypatch.setattr(production, 'load_context', lambda p: (plan, paths, teacher))
    def runtime(plan, folder):
        write(folder / 'runtime.json', {})
        return folder / 'runtime.json'
    monkeypatch.setattr(audit, 'isolated_native', runtime)
    captures, closed = [], []
    class Capture:
        def __init__(self, *args): pass
        def capture(self, request, raw, log):
            captures.append(raw)
            write(raw, dict(complete=False, nativeStatus='SyntheticNativeFailure'))
            log.write_text('original failed recording')
        def close(self): closed.append(True)
    monkeypatch.setitem(sys.modules, 'persistent_capture_v2', SimpleNamespace(PersistentCapture=Capture))
    monkeypatch.setitem(sys.modules, 'replay_evidence', SimpleNamespace(validate_replay=None, terminal=None, normalized=None))
    monkeypatch.setattr(sys, 'argv', ['audit', '--directory', str(directory), '--production'])
    # Avoid changing pytest's signal handlers or parent environment.
    monkeypatch.setattr(audit.signal, 'signal', lambda *a: None)
    monkeypatch.setattr(audit.os, 'environ', dict(audit.os.environ))
    with pytest.raises(RuntimeError, match='exhausted native'): audit.main()
    assert len(captures) == 3 and closed == [True]
    assert all(read(p)['nativeStatus'] == 'SyntheticNativeFailure' for p in captures)
    stop = read(directory / 'audit-stop.json'); assert 'exhausted native' in stop['error']
    receipt = read(directory / 'native-audit/case-000001/result.json')
    assert receipt['status'] == 'native_failed' and len(receipt['nativeAttempts']) == 3
    assert not (directory / 'audit-report.json').exists()
    with sqlite3.connect(paths['real']) as db:
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 1
    preserved = (directory / 'audit-stop.json').read_bytes()
    with pytest.raises(ValueError, match='requires diagnosis'): audit.main()
    assert len(captures) == 3 and (directory / 'audit-stop.json').read_bytes() == preserved
