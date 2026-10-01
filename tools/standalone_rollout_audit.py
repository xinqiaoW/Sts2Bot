"""Continuously audit new rollout compositions against original native actions."""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time

from standalone_rollout_metrics import identity, read, sampled_build, sha, write
from standalone_rollout_provenance import load_native_capture


def isolated_native(plan, directory):
    runtime = read(plan['nativeRuntime'])
    old_game, old_prefix = runtime['game_dir'], runtime['env']['WINEPREFIX']
    game, prefix = directory / 'game', directory / 'prefix'
    shutil.copytree(old_game, game, copy_function=os.link)
    shutil.copytree(old_prefix, prefix, symlinks=True)
    runtime['game_dir'] = str(game)
    runtime['data_dir'] = str(prefix / Path(runtime['data_dir']).relative_to(old_prefix))
    runtime['command'] = [part.replace(old_game, str(game)) for part in runtime['command']]
    runtime['env'].update(WINEPREFIX=str(prefix), DISPLAY='', WAYLAND_DISPLAY='', DOTNET_PROCESSOR_COUNT='1')
    runtime['log_path'] = str(directory / 'native.log')
    for name in ('collector.stop', 'collector.lock', 'combat_solver_test_request.json',
                 'combat_solver_test_result.json', 'combat_solver_test_ready.json'):
        (Path(runtime['data_dir']) / name).unlink(missing_ok=True)
    path = directory / 'runtime.json'; write(path, runtime)
    return path


def ingest(index, paths, expected_teacher=None):
    for name, path in paths.items():
        cursor = index.execute('SELECT value FROM cursors WHERE name=?', (name,)).fetchone()
        last = cursor[0] if cursor else 0
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as database:
            rows = database.execute("SELECT a.id,j.id,j.build_id,j.target,a.result,j.teacher FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE a.id>? AND a.status='complete' ORDER BY a.id LIMIT 128", (last,))
            with index:
                for aid, jid, bid, target, raw, teacher in rows:
                    if expected_teacher is not None and json.loads(teacher) != expected_teacher:
                        raise ValueError('Completed production input uses another teacher')
                    result = json.loads(raw); request = result['collectionRequest']; tid = json.loads(target)['id']
                    fresh = index.execute('INSERT OR IGNORE INTO builds VALUES(?,?,?,?,?)',
                        (bid, name, jid, tid, json.dumps(request))).rowcount
                    new_target = index.execute('INSERT OR IGNORE INTO targets VALUES(?)', (tid,)).rowcount
                    if (fresh and sampled_build(bid)) or new_target:
                        index.execute('INSERT OR IGNORE INTO cases(dataset,job,build,target,request,status) VALUES(?,?,?,?,?,?)',
                                      (name, jid, bid, tid, json.dumps(request), 'pending'))
                    last = aid
                index.execute('INSERT OR REPLACE INTO cursors VALUES(?,?)', (name, last))


def top_up(index):
    total = index.execute('SELECT count(*) FROM builds').fetchone()[0]
    selected = index.execute('SELECT count(DISTINCT build) FROM cases').fetchone()[0]
    needed = math.ceil(total / 100) - selected
    if needed > 0:
        candidates = list(index.execute('SELECT * FROM builds WHERE id NOT IN (SELECT build FROM cases)'))
        candidates.sort(key=lambda r: hashlib.sha256(('rollout-topup:' + r[0]).encode()).hexdigest())
        with index:
            for bid, dataset, job, target, request in candidates[:needed]:
                index.execute('INSERT INTO cases(dataset,job,build,target,request,status) VALUES(?,?,?,?,?,?)',
                              (dataset, job, bid, target, request, 'pending'))


def replay_fixture(native, job, build):
    # The frozen host validates restoration against the native initial observation
    # before it starts fixed-action replay. Keep the complete original recording.
    return dict(attemptId=0, request=native['request'], nativeTrace=native,
                expected=native['result']['trainingObservation'], sourceJobId=job, sourceBuildId=build)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--panel', type=Path, help='Pinned previously quarantined requests; diagnose every entry')
    parser.add_argument('--production', action='store_true', help='Audit queues bound by a separately accepted production plan')
    args = parser.parse_args(); folder = args.directory.resolve(strict=True)
    expected_teacher = None
    if args.production:
        if args.panel is not None: raise ValueError('Production sampling cannot use a replacement input panel')
        if (folder / 'audit-stop.json').exists() or (folder / 'audit-report.json').exists():
            raise ValueError('Stopped production audit requires diagnosis; preserve its evidence')
        from standalone_production_audit import load_context
        plan, paths, expected_teacher = load_context(folder)
    else:
        from run_standalone_rollout import verify_plan
        plan = verify_plan(folder)
        paths = {name: folder / 'soak' / (name + '.sqlite') for name in ('real', 'mutation', 'targeted')}
    panel = None
    prefix = 'audit'
    if args.panel is not None:
        if identity(args.panel) != plan['quarantineInputs']:
            raise ValueError('Quarantine request panel changed')
        panel = read(args.panel)
        prefix = 'quarantine-audit'
    bundle = Path(plan['bundle']); source = Path(plan['nativeSource'])
    for name, expected in plan['nativeFiles'].items():
        if sha(source/name) != expected:
            raise ValueError('Native recorder source changed: ' + name)
    sys.path.insert(0, str(source)); sys.path.insert(0, str(source / 'experiments/native-trace-probe'))
    # Use the already validated native observation implementation, unchanged.
    PersistentCapture = load_native_capture(plan)
    from replay_evidence import validate_replay, terminal, normalized
    os.environ.update(STS2_NATIVE_STARTUP_LOCK_DIR=str(folder / 'audit-startup-slots'),
                      STS2_NATIVE_STARTUP_SLOTS='1', TMPDIR=str(folder), DISPLAY='', WAYLAND_DISPLAY='')
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda signum, frame: (_ for _ in ()).throw(KeyboardInterrupt('audit stopped')))
    audit_dir = folder / ('native-audit' if panel is None else prefix); audit_dir.mkdir(exist_ok=True)
    with (audit_dir / 'audit.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        runtime = audit_dir / 'runtime.json'
        if not runtime.exists():
            runtime = isolated_native(plan, audit_dir)
        index = sqlite3.connect(audit_dir / 'index.sqlite')
        index.executescript('''
            CREATE TABLE IF NOT EXISTS cursors(name TEXT PRIMARY KEY,value INTEGER);
            CREATE TABLE IF NOT EXISTS builds(id TEXT PRIMARY KEY,dataset TEXT,job TEXT,target TEXT,request TEXT);
            CREATE TABLE IF NOT EXISTS targets(id TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS cases(id INTEGER PRIMARY KEY,dataset TEXT,job TEXT,build TEXT,target TEXT,
              request TEXT,status TEXT,UNIQUE(dataset,job));
        ''')
        if panel is not None:
            with index:
                for case in panel:
                    request = json.dumps(case['request'])
                    index.execute('INSERT OR IGNORE INTO builds VALUES(?,?,?,?,?)',
                        (case['build'],case['dataset'],case['job'],case['target'],request))
                    index.execute('INSERT OR IGNORE INTO cases(dataset,job,build,target,request,status) VALUES(?,?,?,?,?,?)',
                        (case['dataset'],case['job'],case['build'],case['target'],request,'pending'))
        capture = None
        try:
            write(folder / (prefix + '-ready.json'), dict(ready=True, pid=os.getpid(),
                  productionAudit=args.production, plan=identity(folder / 'plan.json'), updated=time.time()))
            while True:
                if panel is None:
                    ingest(index, paths, expected_teacher)
                    if args.production: top_up(index)
                drained = panel is not None or (folder / 'collection-drained.json').exists()
                if drained and panel is None:
                    # Exhaust incremental pages before declaring sampling complete.
                    while True:
                        previous = list(index.execute('SELECT * FROM cursors ORDER BY name'))
                        ingest(index, paths, expected_teacher)
                        if previous == list(index.execute('SELECT * FROM cursors ORDER BY name')):
                            break
                    top_up(index)
                row = index.execute("SELECT id,dataset,job,build,target,request FROM cases WHERE status='pending' ORDER BY id LIMIT 1").fetchone()
                summary = dict(counts=dict(index.execute('SELECT status,count(*) FROM cases GROUP BY status')),
                               distinctCompletedBuilds=index.execute('SELECT count(*) FROM builds').fetchone()[0],
                               sampledBuilds=index.execute('SELECT count(DISTINCT build) FROM cases').fetchone()[0],
                               updated=time.time(), collectionDrained=drained)
                write(folder / (prefix + '-status.json'), summary)
                if row is None:
                    if drained: break
                    time.sleep(5); continue
                cid, dataset, jid, bid, target, encoded = row
                case = audit_dir / f'case-{cid:06d}'; case.mkdir(exist_ok=True)
                request_path = case / 'request.json'
                if not request_path.exists():
                    write(request_path, dict(request=json.loads(encoded), dataset=dataset, sourceJobId=jid, sourceBuildId=bid))
                native = None; attempts = []
                for attempt in range(1, 4):
                    raw, log = case / f'native-{attempt}.json', case / f'native-{attempt}.log'
                    if not raw.exists():
                        if capture is None:
                            capture = PersistentCapture(audit_dir, runtime, bundle / 'progress-snapshot.json', plan['traceDll']['path'])
                        capture.capture(request_path, raw, log)
                    recorded = read(raw); attempts.append(identity(raw))
                    if recorded['complete']:
                        native = recorded; break
                receipt = dict(caseId=cid, dataset=dataset, job=jid, build=bid, target=target, nativeAttempts=attempts)
                status = 'native_failed'
                if native:
                    if normalized(native['request']) != normalized(json.loads(encoded)):
                        raise ValueError('Native audit changed the sampled request')
                    assert native['progressSnapshotSha256'] == sha(bundle / 'progress-snapshot.json')
                    assert native['traceModSha256'] == plan['traceDll']['sha256']
                    trace = Path(native['directory']) / (native['request']['runId'] + '.jsonl')
                    assert [json.loads(line) for line in trace.read_text().splitlines()] == native['events']
                    fixture, replay_log = case / 'replay.json', case / 'replay.log'
                    if replay_log.exists():
                        raise RuntimeError('Interrupted replay requires review; refusing to overwrite it')
                    write(fixture, replay_fixture(native, jid, bid))
                    command = [read(bundle / 'runtime-template.json')['dotnet'], str(bundle / 'host/SimulatorPrototype.dll'),
                               read(bundle / 'runtime-template.json')['game_dir'], '--replay-native-request', str(fixture),
                               str(bundle / 'progress-snapshot.json')]
                    try:
                        with replay_log.open('x') as output:
                            execution = subprocess.run(command, stdout=output, stderr=subprocess.STDOUT,
                                env={**os.environ, 'DOTNET_PROCESSOR_COUNT': '1', 'DOTNET_TieredCompilation': '0'}, timeout=120)
                        if execution.returncode:
                            raise ValueError('Replay host failed')
                        receipt.update(validate_replay(native, terminal(replay_log)))
                        status = 'matched'
                    except (ValueError, AssertionError, subprocess.TimeoutExpired) as error:
                        status = 'mismatch'; receipt['error'] = str(error)
                        write(folder / 'audit-stop.json', dict(caseDirectory=str(case), error=str(error), build=bid,
                              action='Drain collection and hold all campaign results pending diagnosis'))
                    receipt.update(replay=identity(replay_log), fixture=identity(fixture), command=command)
                receipt['status'] = status; write(case / 'result.json', receipt)
                with index:
                    index.execute('UPDATE cases SET status=? WHERE id=?', (status, cid))
                if status == 'mismatch':
                    raise RuntimeError('Fixed-action audit mismatch: ' + str(case))
                if args.production and status == 'native_failed':
                    raise RuntimeError('Selected production sample exhausted native recording attempts: ' + str(case))
            cases = [read(p) for p in sorted(audit_dir.glob('case-*/result.json'))]
            matched = [c for c in cases if c['status'] == 'matched']
            total = index.execute('SELECT count(*) FROM builds').fetchone()[0]
            target_count = len({c['target'] for c in matched})
            passed = (bool(cases) and len(matched) == len(cases) and
                      ((len(cases) == len(panel)) if panel is not None else
                       (len({c['build'] for c in matched}) >= math.ceil(total / 100) and target_count == 80)))
            write(folder / (prefix + '-report.json'), dict(passed=passed, distinctCompletedBuilds=total,
                  sampledBuilds=len({c['build'] for c in matched}), matchedCases=len(matched),
                  targets=target_count, checkpoints=sum(c['checkpoints'] for c in matched),
                  failures=[c for c in cases if c['status'] != 'matched'],
                  caseEvidence=[identity(p) for p in sorted(audit_dir.glob('case-*/result.json'))],
                  policy=('Every pinned previously quarantined request must obtain a complete native recording and match the frozen host.' if panel is not None else
                          'Hash-selected new compositions plus target coverage and deterministic final top-up to at least 1%; every selected successful native recording must match. Native failures do not pass.')))
        except BaseException as error:
            if args.production:
                write(folder / 'audit-stop.json', dict(error=repr(error), updated=time.time(),
                      action='Drain formal collection and retain all output for diagnosis'))
            raise
        finally:
            if capture is not None:
                capture.close()
            index.close()


if __name__ == '__main__':
    main()
