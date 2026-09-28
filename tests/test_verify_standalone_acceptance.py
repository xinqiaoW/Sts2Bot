"""Formal readiness must recheck states/resources behind successful summaries."""
import json
import fcntl
import shutil
import sqlite3
from types import SimpleNamespace
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import verify_standalone_acceptance as gate
from standalone_rollout_metrics import identity, write
from test_terminal_state_evidence import terminal_case
import replay_evidence


def sample(tmp_path):
    native, result = terminal_case()
    bundle = tmp_path / 'bundle'
    (bundle / 'host').mkdir(parents=True)
    host = bundle / 'host/SimulatorPrototype.dll'; host.write_bytes(b'unit-host')
    progress = bundle / 'progress-snapshot.json'; progress.write_text('{}')
    native['progressSnapshotSha256'] = identity(progress)['sha256']
    first = native['events'][0]['value']
    first.update(reusableProcess=True, runId=native['request']['runId'],
                 progressSnapshotSha256=native['progressSnapshotSha256'])
    native['directory'] = str(tmp_path / 'native'); Path(native['directory']).mkdir()
    write(bundle / 'configs/teacher.json', native['teacher'])
    raw = tmp_path / 'raw.json'; write(raw, native)
    trace = Path(native['directory']) / (native['request']['runId'] + '.jsonl')
    trace.write_text(''.join(json.dumps(e) + '\n' for e in native['events']))
    fixture = tmp_path / 'fixture.json'; write(fixture, {'nativeTrace': native, 'request': native['request']})
    log = tmp_path / 'replay.log'; log.write_text(json.dumps(result) + '\n')
    receipt = dict(status='matched', nativeAttempts=[identity(raw)], fixture=identity(fixture), replay=identity(log),
                   command=['dotnet', str(host)], **replay_evidence.validate_replay(native, result))
    plan = {'bundle': str(bundle), 'traceDll': {'sha256': native['traceModSha256']}}
    return receipt, native['request'], plan, native, result


def test_native_sample_rechecks_full_states_and_terminal(tmp_path):
    receipt, request, plan, _, _ = sample(tmp_path)
    assert gate.validate_sample(receipt, request, plan, replay_evidence)['checkpoints'] == 41


@pytest.mark.parametrize('change', ['state', 'terminal', 'play_pile', 'raw_trace', 'wrong_request',
                                   'wrong_host', 'recaptured', 'receipt_count', 'receipt_flag', 'wrong_progress_ack'])
def test_matched_receipt_cannot_hide_changed_native_evidence(tmp_path, change):
    receipt, request, plan, native, result = sample(tmp_path)
    if change == 'state': result['battle']['compared'][0]['actual'] += ';changed'
    elif change == 'terminal': result['finalCombatState'] += ';changed'
    elif change == 'play_pile':
        point = result['battle']['compared'][0]
        point['actual'] = point['actual'].replace(';V=', ';V=BURN')
    elif change == 'raw_trace':
        (Path(native['directory']) / (native['request']['runId'] + '.jsonl')).write_text('{}\n')
    elif change == 'wrong_request': request = {**request, 'seed': 'different'}
    elif change == 'wrong_host':
        other = tmp_path / 'other.dll'; other.write_bytes(b'other'); receipt['command'][1] = str(other)
    elif change == 'recaptured': receipt['nativeAttempts'].append(receipt['nativeAttempts'][0])
    elif change == 'receipt_count': receipt['checkpoints'] += 1
    elif change == 'receipt_flag': receipt['playPileStateVerified'] = False
    elif change == 'wrong_progress_ack':
        native['events'][0]['value']['progressSnapshotSha256'] = 'wrong'
        write(receipt['nativeAttempts'][0]['path'], native)
        receipt['nativeAttempts'][0] = identity(receipt['nativeAttempts'][0]['path'])
    if change in ('state', 'terminal', 'play_pile'):
        Path(receipt['replay']['path']).write_text(json.dumps(result) + '\n')
        receipt['replay'] = identity(receipt['replay']['path'])
    with pytest.raises(ValueError):
        gate.validate_sample(receipt, request, plan, replay_evidence)


def resources(tmp_path, *, duration=86400, late=100 * 2**20, available=32 * 2**30, oom=0):
    write(tmp_path / 'launch.json', {'startedAt': 1000})
    path = tmp_path / 'resources.jsonl'
    rows = []
    for i in range(10):
        rows.append(dict(time=1100 + i * (duration - 100) / 9, workerRssBytes=100 * 2**20 if i < 5 else late,
                         availableBytes=available, cgroups=[{'path': '/account', 'memory.events': f'oom_kill {0 if i == 0 else oom}'}]))
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
    return {'resources': identity(path), 'workers': 8, 'wallSeconds': 86400, 'workerMemory': {'healthy': True}}


def test_full_duration_and_stable_sampled_memory_pass(tmp_path):
    assert gate.verify_memory(resources(tmp_path), tmp_path)['healthy']


@pytest.mark.parametrize('change', ['backup_delay', 'leak', 'oom', 'reserve', 'changed_file'])
def test_positive_summary_cannot_hide_resource_failure(tmp_path, change):
    args = {}
    if change == 'backup_delay': args['duration'] = 85000  # Report wall time still claims 24 h.
    elif change == 'leak': args['late'] = 1024 * 2**20
    elif change == 'oom': args['oom'] = 1
    elif change == 'reserve': args['available'] = 15 * 2**30
    report = resources(tmp_path, **args)
    if change == 'changed_file': Path(report['resources']['path']).write_text('{}\n')
    with pytest.raises(ValueError): gate.verify_memory(report, tmp_path)


def test_unfinished_rollout_cannot_authorize_formal_collection(tmp_path):
    with pytest.raises(FileNotFoundError): gate.verify_acceptance(tmp_path)
    write(tmp_path / 'final-report.json', {'passed': False})
    with pytest.raises(ValueError, match='Completed rollout acceptance required'):
        gate.verify_acceptance(tmp_path)


def test_final_pass_flag_does_not_override_live_controller_ownership(tmp_path):
    write(tmp_path / 'final-report.json', {'passed': True})
    with (tmp_path / 'controller.lock').open('a+') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(ValueError, match='active owner'):
            gate.verify_acceptance(tmp_path)


def test_remaining_handoff_evidence_is_checked_for_an_already_validated_candidate(tmp_path, monkeypatch):
    # Candidate provenance is covered by test_standalone_rollout_provenance.
    # Here exercise real files, SQLite queues/backups and native replay parsing
    # across the remaining promotion checks with explicitly synthetic evidence.
    from test_standalone_rollout import batch
    from standalone_rollout_metrics import choose_workers
    first, _, plan, _, _ = sample(tmp_path / 'seed')
    bundle = Path(plan['bundle'])
    phase = tmp_path / 'soak'; phase.mkdir()
    (tmp_path / 'controller.lock').touch()
    for i in range(8):
        data = phase / 'workers' / str(i); data.mkdir(parents=True)
        (data / 'collector.lock').touch()
        write(phase / f'runtime-{i}.json', {'data_dir': str(data)})
    paths = {}
    for name in ('real', 'mutation', 'targeted'):
        path = phase / (name + '.sqlite'); paths[name] = path
        path.with_suffix('.pool.lock').touch()
        with sqlite3.connect(path) as db:
            db.executescript('''
                CREATE TABLE jobs(id TEXT PRIMARY KEY,status TEXT,build_id TEXT,target TEXT,result TEXT);
                CREATE TABLE builds(id TEXT PRIMARY KEY);
                CREATE TABLE attempts(id INTEGER PRIMARY KEY);
                CREATE TABLE job_quarantines(job_id TEXT PRIMARY KEY);
            ''')
    case_evidence = []
    with sqlite3.connect(paths['real']) as db:
        for i in range(80):
            case_path = tmp_path / 'native-audit' / f'case-{i}'
            receipt, request, _, native, replay = sample(case_path)
            target, build, job = f'target-{i}', f'build-{i}', f'job-{i:05}'
            request['encounterId'] = target
            request['runId'] = f'{i:032x}'
            native['request'] = request; native['result']['runId'] = request['runId']
            native['events'][0]['value']['runId'] = request['runId']
            write(receipt['nativeAttempts'][0]['path'], native)
            receipt['nativeAttempts'] = [identity(receipt['nativeAttempts'][0]['path'])]
            trace = Path(native['directory']) / (request['runId'] + '.jsonl')
            trace.write_text(''.join(json.dumps(e) + '\n' for e in native['events']))
            write(receipt['fixture']['path'], {'nativeTrace': native, 'request': request})
            receipt['fixture'] = identity(receipt['fixture']['path'])
            receipt.update(dataset='real', job=job, build=build, target=target,
                           command=['dotnet', str(bundle / 'host/SimulatorPrototype.dll')])
            result_path = case_path / 'result.json'; write(result_path, receipt)
            case_evidence.append(identity(result_path))
            db.execute('INSERT INTO builds VALUES(?)', (build,))
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?)', (job, 'complete', build,
                       json.dumps({'id': target}), json.dumps({'collectionRequest': request})))
        db.executemany('INSERT INTO jobs VALUES(?,?,?,?,?)',
                       [(f'job-{i:05}', 'complete', f'build-{i%80}', '{}', '{}') for i in range(80, 10000)])
    audit_path = tmp_path / 'audit-report.json'
    write(audit_path, dict(passed=True, failures=[], caseEvidence=case_evidence, matchedCases=80,
                          sampledBuilds=80, distinctCompletedBuilds=80, targets=80, checkpoints=80 * 41))
    copies = []
    for name, path in paths.items():
        target = tmp_path / 'backups' / name / path.name; target.parent.mkdir(parents=True)
        shutil.copyfile(path, target); copies.append(identity(target))
    backup_report = tmp_path / 'backup-restoration.json'; write(backup_report, {'passed': True, 'databases': copies})
    reports = [batch(8), batch(8)]
    for i, report in enumerate(reports): write(tmp_path / f'ladder-{i:02d}-8/report.json', report)
    selection = choose_workers(reports); write(tmp_path / 'concurrency-selection.json', selection)
    soak = {**resources(phase), 'workers': 8, 'completed': 10000, 'quarantined': 0, 'counts': {'complete': 10000}}
    write(phase / 'report.json', soak)
    rollback = dict(bundle=str(bundle), passed=True, complete=True, nativeHistoryPreserved=True,
                    standaloneHistoryPreserved=True, handoffBackupsVerified=True,
                    phases=[{'phase': name, 'exitCode': 0, 'locksReleased': True, 'after': {'counts': {'complete': 1}}}
                            for name in ('native-before', 'standalone-stop-drain', 'native-after-rollback')])
    rollback_path = tmp_path / 'rollback-report.json'; write(rollback_path, rollback)
    plan.update(concurrencyOrder=[8, 8], releaseManifest={'alreadyVerified': 'release'},
                correctnessAudit={'alreadyVerified': 'correctness'})
    write(tmp_path / 'final-report.json', dict(passed=True, selection=selection, releaseManifest=plan['releaseManifest'],
          correctnessAudit=plan['correctnessAudit'], soak=identity(phase / 'report.json'), audit=identity(audit_path),
          backupRestoration=identity(backup_report), rollback=identity(rollback_path)))
    monkeypatch.setattr(gate, 'verify_plan', lambda folder: plan)
    monkeypatch.setattr(gate, 'load_module', lambda name, path:
                        SimpleNamespace(verify=lambda bundle: None) if name == 'accepted_release' else replay_evidence)
    accepted = gate.verify_acceptance(tmp_path)
    assert accepted['passed'] and accepted['completed'] == 10000 and accepted['nativeAuditedBuilds'] == 80
    # A post-acceptance queue edit must fail even though every report still says passed.
    with sqlite3.connect(paths['real']) as db:
        db.execute("UPDATE jobs SET result='changed' WHERE id='job-00000'")
    with pytest.raises(AssertionError): gate.verify_acceptance(tmp_path)
