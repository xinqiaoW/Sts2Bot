"""Run paired concurrency batches, then a guarded 24-hour isolated collection."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import statistics
import subprocess
import sys
import time

import psutil
from standalone_rollout_metrics import (choose_workers, combine_batches, identity, read, resource_snapshot,
                                        search_metrics, sha, soak_gate, write)
from standalone_rollout_provenance import verify_candidate


def owned_exec(arguments):
    """Install parent-death SIGTERM in a fresh interpreter, then exec the pool."""
    import ctypes
    parent = int(arguments[0])
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0):
        raise OSError(ctypes.get_errno(), 'Cannot install parent-death signal')
    if os.getppid() != parent:
        raise SystemExit(125)
    os.execvp(arguments[1], arguments[1:])


def owned_command(command):
    return [sys.executable, str(Path(__file__).resolve()), '--owned-exec', str(os.getpid()), *command]


def counts(paths):
    result = Counter()
    for path in paths:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            result.update(dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status')))
    return dict(result)


def verify_plan(folder):
    plan = read(folder / 'plan.json')
    if plan.get('schema') != 'standalone-rollout/v2':
        raise ValueError('Rollout requires current full-state correctness binding')
    for entry in [plan['releaseManifest'], plan['source'], plan['pairedInputs'], plan['benchmark'], *plan['templates'].values()]:
        if identity(entry['path']) != entry:
            raise ValueError('Frozen input changed: ' + entry['path'])
    for name, expected in plan['control'].items():
        if sha(folder / 'control' / name) != expected:
            raise ValueError('Frozen controller changed: ' + name)
    if plan.get('quarantineInputs') and identity(plan['quarantineInputs']['path']) != plan['quarantineInputs']:
        raise ValueError('Frozen quarantine panel changed')
    verify_candidate(plan)
    return plan


def clone_database(source, target):
    if target.exists():
        raise FileExistsError(target)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as src, sqlite3.connect(target) as dst:
        src.backup(dst, pages=4096)


def make_runtimes(bundle, phase, workers):
    result = []
    for i in range(workers):
        runtime = read(bundle / 'runtime-template.json')
        data = phase / 'workers' / f'{i:02d}'
        data.mkdir(parents=True)
        runtime.update(data_dir=str(data), log_path=str(data / 'host.log'),
                       env={'DOTNET_PROCESSOR_COUNT': '1', 'TMPDIR': str(phase), 'DISPLAY': '', 'WAYLAND_DISPLAY': ''})
        path = phase / f'runtime-{i:02d}.json'; write(path, runtime); result.append(path)
    return result


def verify_released(paths, runtimes):
    for path in [p.with_suffix('.pool.lock') for p in paths] + [Path(read(p)['data_dir']) / 'collector.lock' for p in runtimes]:
        with path.open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if counts(paths).get('running', 0):
        raise RuntimeError('Jobs remain leased after pool drain')


def summarize_phase(phase, paths, workers, wall, peak_rss, cpu_seconds, samples, exit_code):
    metrics = search_metrics(sorted((phase / 'workers').glob('*/host.log')))
    cases = {}; failed = 0; completed = 0
    for path in paths:
        with sqlite3.connect(path.as_uri() + '?mode=ro', uri=True) as db:
            failed += db.execute("SELECT count(*) FROM attempts WHERE status!='complete'").fetchone()[0]
            for jid, status, result in db.execute('SELECT id,status,result FROM jobs WHERE attempts>0'):
                value = json.loads(result) if result else {}
                case = {'complete': status == 'complete', 'status': status}
                if case['complete']:
                    completed += 1
                    observation = value['trainingObservation']
                    case.update(netHpLoss=observation['netHpLoss'], playerDied=observation['playerDied'],
                                runId=value['runId'], elapsedMilliseconds=value['elapsedMilliseconds'],
                                **metrics.get(value['runId'], {}))
                cases[jid] = case
    count = counts(paths)
    complete_cases = [c for c in cases.values() if c['complete']]
    coverage = sum(c.get('firstSearch') is not None for c in complete_cases) / max(1, completed)
    report = dict(phase=phase.name, workers=workers, wallSeconds=wall, completed=completed,
                  failedAttempts=failed, quarantined=count.get('quarantined', 0), counts=count,
                  sampledPeakRssBytes=peak_rss, sampledCpuSeconds=cpu_seconds,
                  validLabelsPerHour=completed * 3600 / wall, metricCoverage=coverage, cases=cases,
                  resources=identity(phase / 'resources.jsonl'), exitCode=exit_code,
                  passed=exit_code == 0 and not count.get('failed', 0) and not count.get('running', 0) and coverage >= .99)
    if samples:
        q = max(1, len(samples) // 4)
        early = statistics.median(x['workerRssBytes'] for x in samples[:q])
        late = statistics.median(x['workerRssBytes'] for x in samples[-q:])
        report['workerMemory'] = dict(earlyMedianBytes=early, lateMedianBytes=late,
                                    healthy=late <= early + max(128 * 2**20, early * .5))
    write(phase / 'report.json', report)
    return report


def backup_all(phase, paths):
    from tools.local_backup import backup_once
    return {p.stem: backup_once(p, phase / 'backups' / p.stem, phase / f'{p.stem}-backup.json') for p in paths}


def run_pool(folder, bundle, phase, paths, workers, cpus, *, seconds=None, auditor=None, diagnostic_auditor=None):
    runtimes = make_runtimes(bundle, phase, workers)
    command = [sys.executable, str(bundle / 'release_tool.py'), 'run', '--bundle', str(bundle),
               '--module', 'tools.collect_parallel', '--', '--db', str(paths[0]),
               '--config', str(bundle / 'configs/real-runs-8s.json'), '--teacher', str(bundle / 'teacher.json'),
               '--runtimes', *map(str, runtimes), '--reserve-gib', '16', '--worker-start-gib', '2',
               '--limit-per-worker', '1000000']
    if len(paths) == 3:
        command += ['--fallback-db', str(paths[1]), '--targeted-db', str(paths[2])]
    start = time.time()
    if seconds is not None:
        command += ['--stop-at', str(start + seconds)]
    command = ['taskset', '-c', ','.join(map(str, cpus)), *command]
    env = {**os.environ, 'TMPDIR': str(phase), 'PYTHONDONTWRITEBYTECODE': '1',
           'DISPLAY': '', 'WAYLAND_DISPLAY': ''}
    peak_rss = 0; cpu = {}; samples = []; failure = None
    before = resource_snapshot()
    write(phase / 'launch.json', dict(command=command, startedAt=start, cpus=cpus, resources=before))
    with (phase / 'pool.log').open('x') as log, (phase / 'resources.jsonl').open('x') as resources, ThreadPoolExecutor(max_workers=1) as executor:
        process = subprocess.Popen(owned_command(command), cwd=phase, env=env, stdout=log, stderr=subprocess.STDOUT,
                                   start_new_session=True)
        write(phase / 'owner.json', {'pid': process.pid, 'created': psutil.Process(process.pid).create_time()})
        next_status = start; next_backup = start + 1800; pending_backup = None
        try:
            while process.poll() is None:
                snapshot = resource_snapshot()
                rss = 0; worker_rss = 0
                try:
                    owned = psutil.Process(process.pid)
                    for child in [owned, *owned.children(recursive=True)]:
                        try:
                            memory = child.memory_info().rss; rss += memory
                            if 'damage_model.cli' in child.cmdline():
                                worker_rss += memory
                            t = child.cpu_times(); cpu[(child.pid, child.create_time())] = t.user + t.system
                        except psutil.Error:
                            pass
                except psutil.NoSuchProcess:
                    pass
                snapshot.update(rssBytes=rss, workerRssBytes=worker_rss, cpuSeconds=sum(cpu.values()))
                resources.write(json.dumps(snapshot) + '\n'); resources.flush()
                peak_rss = max(peak_rss, rss)
                # Compare steady worker memory only after all staggered worker starts.
                if time.time() - start > workers * 2 + 30 and worker_rss:
                    samples.append({'workerRssBytes': worker_rss})
                if snapshot['availableBytes'] < 16 * 2**30:
                    raise RuntimeError('Effective cgroup/host memory reserve fell below 16 GiB')
                for earlier, current in zip(before['cgroups'], snapshot['cgroups']):
                    old = dict(line.split() for line in earlier.get('memory.events', '').splitlines())
                    new = dict(line.split() for line in current.get('memory.events', '').splitlines())
                    if int(new.get('oom_kill', 0)) > int(old.get('oom_kill', 0)):
                        raise RuntimeError('OOM kill observed in shared cgroup; drain and review resource budget')
                if shutil.disk_usage(folder).free < 50 * 2**30:
                    raise RuntimeError('Less than 50 GiB free; drain before evidence space is exhausted')
                if (folder / 'STOP').exists():
                    raise RuntimeError('Explicit campaign stop marker')
                if (folder / 'audit-stop.json').exists():
                    raise RuntimeError('Native audit discrepancy; all campaign output held for review')
                if auditor is not None and auditor.poll() is not None:
                    raise RuntimeError('Native audit worker exited before collection drain')
                if diagnostic_auditor is not None and diagnostic_auditor.poll() not in (None, 0):
                    raise RuntimeError('Quarantine diagnostic worker failed')
                if time.time() >= next_status:
                    count = counts(paths)
                    if count.get('quarantined', 0) >= 10 and count['quarantined'] / max(1, count.get('complete', 0) + count['quarantined']) > .01:
                        raise RuntimeError('More than 1% of settled jobs quarantined')
                    write(folder / 'status.json', dict(state='collecting', phase=phase.name, workers=workers,
                          startedAt=start, updated=time.time(), elapsedSeconds=time.time()-start,
                          counts=count, poolPid=process.pid, sampledPeakRssBytes=peak_rss,
                          resources=snapshot, productionDeployed=False))
                    next_status = time.time() + 15
                if pending_backup is not None and pending_backup.done():
                    write(phase / 'latest-backups.json', pending_backup.result()); pending_backup = None
                if seconds is not None and time.time() >= next_backup and pending_backup is None:
                    pending_backup = executor.submit(backup_all, phase, paths); next_backup = time.time() + 1800
                time.sleep(1)
        except BaseException as error:
            failure = error
            for runtime in runtimes:
                (Path(read(runtime)['data_dir']) / 'collector.stop').touch()
            process.send_signal(signal.SIGTERM)
        finally:
            try:
                process.wait(timeout=190)
            except subprocess.TimeoutExpired:
                # The pool has its own bounded drain. Preserve abnormal termination as failure.
                process.send_signal(signal.SIGINT)
                process.wait(timeout=20)
            if pending_backup is not None:
                write(phase / 'latest-backups.json', pending_backup.result())
    report = summarize_phase(phase, paths, workers, time.time()-start, peak_rss, sum(cpu.values()), samples, process.returncode)
    try:
        verify_released(paths, runtimes)
    except BaseException as error:
        report.update(passed=False, drainError=str(error), originalError=str(failure) if failure else None)
        write(phase / 'report.json', report)
        raise
    if failure is not None:
        raise failure
    if not report['passed']:
        raise RuntimeError('Pool execution or diagnostic completeness failed: ' + str(phase))
    return report


def prepare_paired(plan, bundle, phase, input_file=None):
    from damage_model.catalog import Catalog
    from damage_model.schema import Build
    from damage_model.store import Store
    from damage_model.target_scope import require_policy
    store = Store(phase / 'real.sqlite')
    catalog = Catalog.load(bundle / 'catalogs/game-0.111.0.raw.json', bundle / 'configs/real-runs-8s.json')
    require_policy(store, catalog.config)
    for case in read(input_file or plan['pairedInputs']['path']):
        store.schedule(Build.from_dict(case['build']), [case['target']], [case['seed']], read(bundle / 'teacher.json'))
    store.db.close()
    return [phase / 'real.sqlite']


def supplementary_inputs(plan, folder, number, used):
    """Add inputs, never replace old measurements or select by battle outcome."""
    from collections import defaultdict
    from damage_model.schema import digest
    path = folder / f'supplement-{number:02d}-inputs.json'
    if path.exists():
        cases = read(path)
        if used & {c['jobId'] for c in cases}:
            raise ValueError('Supplement repeats an already measured input')
        return path
    source = Path(plan['templates']['real']['path'])
    by_target = defaultdict(list)
    with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as db:
        bodies = {bid: json.loads(body) for bid, body in db.execute('SELECT id,body FROM builds')}
        teacher = read(Path(plan['bundle'])/'teacher.json')
        for bid, encoded, seed in db.execute('SELECT build_id,target,MIN(seed) FROM jobs GROUP BY build_id,target'):
            target = json.loads(encoded); jid = digest([bid, target['id'], seed, teacher])
            if jid in used: continue
            build = bodies[bid]
            by_target[target['id']].append(dict(jobId=jid, build=build, target=target, seed=seed,
                rank=digest(['rollout-supplement-v1', number, jid]),
                complexity=len(build['cards']) + 2*len(build['relics'])))
    if len(by_target) != 80:
        raise ValueError('Supplement cannot cover all formal targets')
    cases = []
    for tid, candidates in sorted(by_target.items()):
        ordinary = min(candidates, key=lambda c:c['rank'])
        complex_case = min((c for c in candidates if c['jobId'] != ordinary['jobId']),
                           key=lambda c:(-c['complexity'],c['rank']))
        cases.extend([ordinary, complex_case])
    cases.sort(key=lambda c:digest(['supplement-order',c['jobId']]))
    write(path, cases)
    write(path.with_suffix('.selection.json'), dict(inputs=identity(path), source=plan['templates']['real'],
          policy='Additional hash-selected and complex source-window inputs per target; excludes previously measured job IDs, never filters on outcomes. All old results remain in the combined selection denominator.'))
    return path


def verify_backup_restore(paths, backups):
    checks = []
    for source in paths:
        entry = backups[source.stem]
        target = Path(entry['directory']) / source.name
        assert sha(target) == entry['manifest']['sha256']
        with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as a, sqlite3.connect(target.as_uri() + '?mode=ro', uri=True) as b:
            assert b.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            for table, order in [('jobs', 'id'), ('attempts', 'id'), ('builds', 'id'), ('job_quarantines', 'job_id')]:
                left = a.execute(f'SELECT * FROM {table} ORDER BY {order}')
                right = b.execute(f'SELECT * FROM {table} ORDER BY {order}')
                while True:
                    x, y = left.fetchmany(100), right.fetchmany(100)
                    assert x == y, (source, table)
                    if not x: break
        checks.append(identity(target))
    return {'passed': True, 'databases': checks}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args(); folder = args.directory.resolve(strict=True)
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Controller interrupted; drain owned work')
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    with (folder / 'controller.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = verify_plan(folder); bundle = Path(plan['bundle'])
        sys.path.insert(0, str(bundle))
        spec = importlib.util.spec_from_file_location('release', bundle / 'release_tool.py')
        release = importlib.util.module_from_spec(spec); spec.loader.exec_module(release); release.verify(bundle)
        initial = resource_snapshot()
        if initial['cpuQuotaCores'] < max(plan['concurrencyOrder']):
            raise ValueError('CPU quota below planned ladder; prepare an explicitly smaller ladder')
        allowed = sorted(os.sched_getaffinity(0))
        cpus = allowed[64:96] if len(allowed) >= 96 else allowed[:32]
        write(folder / 'controller.json', dict(pid=os.getpid(), startedAt=time.time(), resourceSnapshot=initial, cpus=cpus))
        auditor = None
        quarantine_auditor = None
        try:
            reports = []
            for index, workers in enumerate(plan['concurrencyOrder']):
                phase = folder / f'ladder-{index:02d}-{workers}'
                if (phase / 'report.json').exists():
                    reports.append(read(phase / 'report.json')); continue
                phase.mkdir()  # Incomplete phases require diagnosis, never silently restart them.
                paths = prepare_paired(plan, bundle, phase)
                reports.append(run_pool(folder, bundle, phase, paths, workers, cpus))
            selection = choose_workers(reports)
            # More measured inputs resolve an undersized timed-search subset;
            # the expansion, failure and label-quality thresholds stay fixed.
            used = set(reports[0]['cases'])
            for extra in range(1, 5):
                if selection['passed'] or all(c['matchedTimedSearches'] >= 30 for c in selection['candidates']):
                    break
                if any(r['failedAttempts'] or r['quarantined'] or not r['passed'] for r in reports):
                    break
                write(folder/f'selection-before-supplement-{extra:02d}.json', selection)
                inputs = supplementary_inputs(plan, folder, extra, used)
                extra_reports = []
                for index, workers in enumerate(plan['concurrencyOrder']):
                    phase = folder / f'supplement-{extra:02d}-{index:02d}-{workers}'
                    if (phase/'report.json').exists():
                        extra_reports.append(read(phase/'report.json')); continue
                    phase.mkdir()
                    paths = prepare_paired(plan, bundle, phase, inputs)
                    extra_reports.append(run_pool(folder, bundle, phase, paths, workers, cpus))
                reports = combine_batches(reports, extra_reports)
                used.update(reports[0]['cases'])
                selection = choose_workers(reports)
            write(folder / 'concurrency-selection.json', selection)
            if not selection['passed']:
                raise RuntimeError('No concurrency passed throughput and search-quality gates')
            from standalone_rollout_audit import isolated_native
            rollback_native = folder / 'rollback-native'; rollback_native.mkdir()
            rollback_runtime = isolated_native(plan, rollback_native)
            rollback_command = [sys.executable, str(folder/'control/run_backend_rollback.py'),
                '--bundle', str(bundle), '--benchmark', plan['benchmark']['path'],
                '--native-runtime', str(rollback_runtime), '--isolated-native-directory', str(rollback_native),
                '--output-root', str(folder), '--report', str(folder/'rollback-report.json')]
            write(folder/'status.json', dict(state='rollback_check', updated=time.time(), selection=selection))
            with (folder/'rollback-driver.log').open('x') as log:
                subprocess.run(rollback_command, cwd=folder, stdout=log, stderr=subprocess.STDOUT, check=True,
                               env={**os.environ, 'DISPLAY': '', 'WAYLAND_DISPLAY': '', 'TMPDIR': str(folder)})
            assert read(folder/'rollback-report.json')['passed']
            phase = folder / 'soak'; phase.mkdir()
            paths = [phase / f'{name}.sqlite' for name in ('real', 'mutation', 'targeted')]
            for path in paths:
                clone_database(Path(plan['templates'][path.stem]['path']), path)
            write(phase / 'session.json', dict(bundle=str(bundle), teacher=str(bundle/'teacher.json'),
                  queues=list(map(str, paths)), source=plan['source'], workers=selection['selectedWorkers'], productionDeployed=False))
            with (folder / 'audit-driver.log').open('x') as log:
                auditor = subprocess.Popen(owned_command([sys.executable, str(folder / 'control/standalone_rollout_audit.py'),
                    '--directory', str(folder)]), cwd=folder, stdout=log, stderr=subprocess.STDOUT,
                    env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': str(folder)}, start_new_session=True)
            write(folder / 'audit-owner.json', {'pid': auditor.pid, 'created': psutil.Process(auditor.pid).create_time()})
            if plan.get('quarantineInputs'):
                with (folder / 'quarantine-audit-driver.log').open('x') as log:
                    quarantine_auditor = subprocess.Popen(owned_command([sys.executable,
                        str(folder / 'control/standalone_rollout_audit.py'), '--directory', str(folder),
                        '--panel', plan['quarantineInputs']['path']]), cwd=folder, stdout=log, stderr=subprocess.STDOUT,
                        env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1', 'TMPDIR': str(folder)}, start_new_session=True)
                write(folder / 'quarantine-audit-owner.json', {'pid': quarantine_auditor.pid,
                      'created': psutil.Process(quarantine_auditor.pid).create_time()})
            report = run_pool(folder, bundle, phase, paths, selection['selectedWorkers'], cpus,
                              seconds=plan['soakSeconds'], auditor=auditor, diagnostic_auditor=quarantine_auditor)
            write(folder / 'collection-drained.json', {'complete': True, 'report': identity(phase / 'report.json')})
            # Audit may have a bounded backlog; stay observable while it finishes.
            while auditor.poll() is None:
                write(folder / 'status.json', dict(state='auditing', updated=time.time(), counts=report['counts']))
                time.sleep(10)
            if auditor.returncode:
                raise RuntimeError('Native sample audit failed')
            audit = read(folder / 'audit-report.json')
            quarantine_audit = None
            if quarantine_auditor is not None:
                while quarantine_auditor.poll() is None:
                    write(folder / 'status.json', dict(state='auditing_quarantines', updated=time.time(), counts=report['counts']))
                    time.sleep(10)
                if quarantine_auditor.returncode:
                    raise RuntimeError('Quarantine audit process failed')
                quarantine_audit = read(folder / 'quarantine-audit-report.json')
            backups = backup_all(phase, paths)
            restored = verify_backup_restore(paths, backups)
            write(folder / 'backup-restoration.json', restored)
            release.verify(bundle)
            verify_plan(folder)
            passed = soak_gate(duration=report['wallSeconds'], completed=report['completed'],
                               failed=report['counts'].get('failed', 0), quarantined=report['quarantined'],
                               running=report['counts'].get('running', 0), audit=audit,
                               healthy_resources=report.get('workerMemory', {}).get('healthy', False), backups_verified=restored['passed'])
            if quarantine_audit is not None:
                passed = passed and quarantine_audit['passed']
            write(folder / 'final-report.json', dict(passed=passed, productionDeployed=False,
                  selection=selection, soak=identity(phase / 'report.json'), audit=identity(folder/'audit-report.json'),
                  backupRestoration=identity(folder/'backup-restoration.json'), releaseManifest=plan['releaseManifest'],
                  correctnessAudit=plan['correctnessAudit'],
                  rollback=identity(folder/'rollback-report.json'),
                  quarantineAudit=identity(folder/'quarantine-audit-report.json') if quarantine_audit is not None else None,
                  scope='Readiness evidence only. Formal session and active pointers remain unchanged.'))
            write(folder / 'status.json', dict(state='passed' if passed else 'failed', updated=time.time(), counts=report['counts']))
        except BaseException as error:
            write(folder / 'status.json', dict(state='blocked', updated=time.time(), error=str(error), productionDeployed=False))
            (folder / 'STOP').touch()
            if auditor is not None and auditor.poll() is None:
                auditor.send_signal(signal.SIGTERM)
                auditor.wait(timeout=190)
            if quarantine_auditor is not None and quarantine_auditor.poll() is None:
                quarantine_auditor.send_signal(signal.SIGTERM)
                quarantine_auditor.wait(timeout=190)
            raise


if __name__ == '__main__':
    if sys.argv[1:2] == ['--owned-exec']:
        owned_exec(sys.argv[2:])
    else:
        main()
