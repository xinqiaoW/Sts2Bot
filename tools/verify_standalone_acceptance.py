"""Independently check the evidence required to promote a frozen collector."""
import argparse
from contextlib import ExitStack, closing
import fcntl
import importlib.util
import math
from pathlib import Path
import sqlite3
import statistics

from standalone_rollout_metrics import choose_workers, combine_batches, identity, read, soak_gate
from standalone_rollout_provenance import checked_identity, require
from run_standalone_rollout import verify_plan, verify_backup_restore


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


def verified_report(entry):
    checked_identity(entry)
    return read(entry['path'])


def validate_sample(case, expected_request, plan, replay):
    """Revisit original native events and replay states, not receipt flags."""
    require(case['status'] == 'matched', 'Selected native audit did not match')
    require(1 <= len(case['nativeAttempts']) <= 3, 'Native attempt count is invalid')
    native = None
    for entry in case['nativeAttempts']:
        require(native is None, 'Successful native recording was replaced')
        value = verified_report(entry)
        require(replay.normalized(value['request']) == replay.normalized(expected_request),
                'Native audit differs from the completed soak input')
        if value['complete']:
            native = value
    require(native is not None, 'No completed native recording')
    bundle = Path(plan['bundle'])
    teacher = read(bundle / 'configs/teacher.json')
    require(native['teacher'] == teacher, 'Native sample teacher differs from accepted release')
    require(native['traceModSha256'] == plan['traceDll']['sha256'], 'Native sample observer changed')
    require(native['progressSnapshotSha256'] == identity(bundle / 'progress-snapshot.json')['sha256'],
            'Native sample progress changed')
    first = native['events'][0]
    require(first['kind'] == 'initialized' and first['value']['collectorSha256'] == teacher['collector_sha256'],
            'Native sample solver differs from accepted release')
    require(first['value']['assemblySha256'] == plan['traceDll']['sha256'], 'Native observer initialization differs')
    reusable = first['value'].get('reusableProcess')
    if reusable:
        require(first['value']['runId'] == native['request']['runId']
                and first['value']['progressSnapshotSha256'] == native['progressSnapshotSha256'],
                'Native reused process did not restore this request and progress')
    trace = Path(native['directory']) / (native['request']['runId'] + '.jsonl' if reusable else 'trace.jsonl')
    import json
    require([json.loads(line) for line in trace.read_text().splitlines()] == native['events'],
            'Native sample differs from original emitted events')
    fixture = verified_report(case['fixture'])
    require(fixture['nativeTrace'] == native and fixture['request'] == native['request'],
            'Audit replay used a different recording')
    checked_identity(case['replay'])
    require(identity(case['command'][1]) == identity(bundle / 'host/SimulatorPrototype.dll'),
            'Audit replay used a different host')
    stats = replay.validate_replay(native, replay.terminal(case['replay']['path']))
    require(all(case.get(key) == stats[key] for key in ('checkpoints', 'terminalCheckpoints',
                'terminalStateVerified', 'playPileStateVerified')), 'Native audit receipt counts differ')
    return stats


def verify_memory(soak, phase):
    """Recompute steady worker growth and resource failures from sampled values."""
    import json
    checked_identity(soak['resources'])
    launch = read(phase / 'launch.json')
    samples = []; baseline = None; previous = None
    with Path(soak['resources']['path']).open() as stream:
        for line in stream:
            value = json.loads(line)
            require(previous is None or value['time'] >= previous, 'Resource samples are out of order')
            previous = value['time']
            require(value['availableBytes'] >= 16 * 2**30, 'Recorded memory reserve was breached')
            events = {entry['path']: dict(row.split() for row in entry.get('memory.events', '').splitlines())
                      for entry in value['cgroups']}
            if baseline is None: baseline = events
            require(events.keys() == baseline.keys(), 'Resource cgroup hierarchy changed')
            require(all(int(events[key].get('oom_kill', 0)) == int(baseline[key].get('oom_kill', 0))
                        for key in events), 'OOM kill occurred during the soak')
            if value['time'] - launch['startedAt'] > soak['workers'] * 2 + 30 and value['workerRssBytes']:
                samples.append(value['workerRssBytes'])
    require(samples, 'Missing steady worker memory observations')
    quarter = max(1, len(samples) // 4)
    early, late = statistics.median(samples[:quarter]), statistics.median(samples[-quarter:])
    require(late <= early + max(128 * 2**20, early * .5), 'Worker memory growth exceeds gate')
    # Sampling is once per second. A long backup after an early pool exit must
    # not turn a shorter run into the required 24-hour observed collection.
    require(previous - launch['startedAt'] >= 86400 - 1, 'Observed collection did not span 24 hours')
    return dict(earlyMedianBytes=early, lateMedianBytes=late, healthy=True)


def verify_acceptance(folder):
    folder = Path(folder).resolve(strict=True)
    require(read(folder / 'final-report.json').get('passed') is True, 'Completed rollout acceptance required')
    with ExitStack() as locks:
        paths = [folder / 'controller.lock']
        paths += [folder / 'soak' / (name + '.pool.lock') for name in ('real', 'mutation', 'targeted')]
        for path in paths:
            lock = locks.enter_context(path.open('r'))
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error: raise ValueError('Rollout still has an active owner: ' + str(path)) from error
        runtimes = list((folder / 'soak').glob('runtime-*.json'))
        require(runtimes, 'Missing soak runtime ownership evidence')
        for runtime in runtimes:
            path = Path(read(runtime)['data_dir']) / 'collector.lock'
            lock = locks.enter_context(path.open('r'))
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error: raise ValueError('Soak worker still active: ' + str(path)) from error
        return verify_drained_acceptance(folder)


def verify_drained_acceptance(folder):
    folder = Path(folder).resolve(strict=True)
    final_path = folder / 'final-report.json'
    final = read(final_path)
    require(final.get('passed') is True, 'Completed rollout acceptance required')
    plan = verify_plan(folder)
    bundle = Path(plan['bundle'])
    load_module('accepted_release', bundle / 'release_tool.py').verify(bundle)
    require(final['releaseManifest'] == plan['releaseManifest']
            and final['correctnessAudit'] == plan['correctnessAudit'], 'Final acceptance refers to another candidate')
    reports = [read(folder / f'ladder-{i:02d}-{workers}/report.json')
               for i, workers in enumerate(plan['concurrencyOrder'])]
    for number in range(1, 5):
        phases = [folder / f'supplement-{number:02d}-{i:02d}-{workers}/report.json'
                  for i, workers in enumerate(plan['concurrencyOrder'])]
        if not any(p.exists() for p in phases): break
        require(all(p.exists() for p in phases), 'Incomplete concurrency supplement')
        reports = combine_batches(reports, [read(p) for p in phases])
    selection = choose_workers(reports)
    require(selection['passed'] and selection == final['selection'] == read(folder / 'concurrency-selection.json'),
            'Concurrency selection differs from recorded batches')
    soak = verified_report(final['soak'])
    require(soak['workers'] == selection['selectedWorkers'], 'Soak used a different worker count')
    memory = verify_memory(soak, folder / 'soak')
    audit = verified_report(final['audit'])
    backups = verified_report(final['backupRestoration'])
    rollback = verified_report(final['rollback'])
    require(rollback['bundle'] == str(bundle) and all(rollback.get(k) is True for k in
            ('passed', 'complete', 'nativeHistoryPreserved', 'standaloneHistoryPreserved', 'handoffBackupsVerified')),
            'Rollback or history preservation did not pass')
    require([p['phase'] for p in rollback['phases']] == ['native-before', 'standalone-stop-drain', 'native-after-rollback']
            and all(p['exitCode'] == 0 and p['locksReleased'] is True and not p['after']['counts'].get('running', 0)
                    for p in rollback['phases']), 'Rollback phases did not drain successfully')
    for entry in backups['databases']: checked_identity(entry)
    require(len(backups['databases']) == 3 and {Path(e['path']).name for e in backups['databases']}
            == {'real.sqlite', 'mutation.sqlite', 'targeted.sqlite'}, 'Missing queue backup restoration')
    restore_inputs = {Path(entry['path']).stem: {'directory': str(Path(entry['path']).parent),
                      'manifest': {'sha256': entry['sha256']}} for entry in backups['databases']}
    verify_backup_restore([folder / 'soak' / (name + '.sqlite') for name in ('real', 'mutation', 'targeted')], restore_inputs)
    require(soak_gate(duration=soak['wallSeconds'], completed=soak['completed'], failed=soak['counts'].get('failed', 0),
            quarantined=soak['quarantined'], running=soak['counts'].get('running', 0), audit=audit,
            healthy_resources=memory['healthy'], backups_verified=backups['passed']), 'Soak requirements are incomplete')
    replay = load_module('accepted_replay_evidence', folder / 'control/replay_evidence.py')
    cases = [verified_report(entry) for entry in audit['caseEvidence']]
    builds = set(); targets = set(); points = 0; jobs = set(); completed_builds = set(); counts = {}
    import json
    with ExitStack() as connections:
        databases = {}
        for name in ('real', 'mutation', 'targeted'):
            path = folder / 'soak' / (name + '.sqlite')
            db = connections.enter_context(closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)))
            databases[name] = db
            for state, count in db.execute('SELECT status,count(*) FROM jobs GROUP BY status'):
                counts[state] = counts.get(state, 0) + count
            completed_builds.update(row[0] for row in db.execute("SELECT DISTINCT build_id FROM jobs WHERE status='complete'"))
        require(counts == soak['counts'] and counts.get('complete', 0) == soak['completed'],
                'Soak counters differ from actual drained queues')
        for case in cases:
            key = (case['dataset'], case['job'])
            require(key not in jobs, 'Duplicate selected audit job'); jobs.add(key)
            db = databases[case['dataset']]
            row = db.execute('SELECT status,build_id,target,result FROM jobs WHERE id=?', (case['job'],)).fetchone()
            require(row is not None and row[0] == 'complete' and row[1] == case['build']
                    and json.loads(row[2])['id'] == case['target'], 'Audit case does not refer to a completed soak job')
            points += validate_sample(case, json.loads(row[3])['collectionRequest'], plan, replay)['checkpoints']
            builds.add(case['build']); targets.add(case['target'])
    require(audit['passed'] is True and not audit['failures'] and len(cases) == audit['matchedCases']
            and len(builds) == audit['sampledBuilds'] >= math.ceil(len(completed_builds) / 100)
            and len(targets) == audit['targets'] == 80 and audit['distinctCompletedBuilds'] == len(completed_builds)
            and points == audit['checkpoints'], 'Native audit coverage/accounting is incomplete')
    if final.get('quarantineAudit'):
        require(verified_report(final['quarantineAudit'])['passed'] is True, 'Historical failure panel did not pass')
    return dict(passed=True, releaseManifest=plan['releaseManifest'], finalReport=identity(final_path),
                correctnessAudit=plan['correctnessAudit'], selectedWorkers=selection['selectedWorkers'],
                completed=soak['completed'], nativeAuditedBuilds=len(builds), nativeAuditCheckpoints=points,
                productionDeployed=False, scope='Verified readiness evidence; active pointers and queues were not changed.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), 'Refusing to overwrite acceptance verification')
    result = verify_acceptance(args.directory)
    from standalone_rollout_metrics import write
    write(args.output, result)
    print(result)
