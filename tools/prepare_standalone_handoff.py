"""Prepare separate pending queues from verified native rollback snapshots."""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time

from standalone_rollout_metrics import identity, read, write
from standalone_rollout_provenance import checked_identity, require
from verify_standalone_acceptance import verify_acceptance


def validate_teacher_change(previous, teacher):
    identity_keys = {'collector_source', 'collector_sha256', 'execution_backend', 'validation_scope',
                     'standalone_host_sha256', 'standalone_unlock_state', 'progress_snapshot_sha256'}
    require(previous.get('execution_backend', 'native-wine') == 'native-wine', 'Source must be a native teacher queue')
    require(teacher.get('execution_backend') == 'standalone-managed-native'
            and teacher.get('validation_scope') == 'isolated-experiment'
            and teacher.get('standalone_unlock_state') == 'progress-snapshot', 'Expected the original accepted standalone teacher')
    require({k: v for k, v in previous.items() if k not in identity_keys}
            == {k: v for k, v in teacher.items() if k not in identity_keys},
            'Game, label and search policy must remain unchanged')
    require(teacher.get('collector_protocol') == 3 and teacher.get('search_ms') == 8000
            and teacher.get('dop') == 1 and 0 < teacher.get('timeout_seconds', 0) <= 120,
            'Handoff requires protocol 3, 8-second search and DOP 1')


def migrate_queue(source, destination, teacher, catalog, acceptance):
    """Old attempts stay in the snapshot; new teacher jobs retain source links."""
    from damage_model.schema import Build, canonical, digest
    from damage_model.store import Store
    from damage_model.mutations import validate_lineage
    source, destination = Path(source).resolve(strict=True), Path(destination).resolve()
    temporary = destination.with_suffix('.preparing.sqlite')
    require(source != destination and not destination.exists() and not temporary.exists(),
            'Use a new destination; interrupted preparation requires diagnosis')
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as old:
        old.row_factory = sqlite3.Row
        old.execute('BEGIN')
        counts = dict(old.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
        require(not counts.get('running'), 'Drain source leases before handoff')
        require(not set(counts) - {'pending', 'complete', 'quarantined', 'failed', 'excluded_target'}, 'Unknown source job state')
        teachers = [json.loads(r[0]) for r in old.execute('SELECT DISTINCT teacher FROM jobs')]
        require(len(teachers) == 1, 'Expected one native source teacher')
        validate_teacher_change(teachers[0], teacher)
        policy = old.execute("SELECT value FROM collection_settings WHERE key='target_policy'").fetchone()
        require(policy is not None, 'Source target policy is missing')
        policy_name = json.loads(policy[0])['name']
        require(policy_name in ('source_floor_window_v1', 'parent_source_window_v1'), 'Unsupported source target policy')
        pending = list(old.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY created,id"))
        validated = {}
        for row in pending:
            require(row['lease'] is None and row['lease_until'] is None, 'Pending source job still has a lease')
            bid = row['build_id']; target = json.loads(row['target'])
            if bid not in validated:
                raw = old.execute('SELECT body FROM builds WHERE id=?', (bid,)).fetchone()
                require(raw is not None, 'Pending job lost its build')
                build = Build.from_dict(json.loads(raw[0])); require(build.id == bid, 'Source build identity differs')
                catalog.validate(build)
                if policy_name == 'parent_source_window_v1': validate_lineage(old, bid, catalog)
                validated[bid] = (build, {t['id']: t for t in catalog.targets(build)})
            build, targets = validated[bid]
            require(targets.get(target['id']) == target and row['seed'] in catalog.battle_seeds(build.act_id, target['id']),
                    'Pending job differs from formal target or seed policy')
            require(row['id'] == digest([bid, target['id'], row['seed'], teachers[0]]), 'Source job identity differs')
            if policy_name == 'source_floor_window_v1':
                require(old.execute('SELECT 1 FROM target_origins WHERE build_id=? AND target_id=? AND ABS(origin_floor-target_floor)<=2',
                                    (bid, target['id'])).fetchone(), 'Pending target has no recorded source window')
        destination.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(temporary)) as snapshot: old.backup(snapshot)
        store = Store(temporary)
        try:
            new = store.db
            with new:
                for row in old.execute("SELECT * FROM jobs WHERE status IN ('complete','failed','quarantined')"):
                    new.execute('INSERT OR IGNORE INTO prior_collected_inputs VALUES(?,?,?,?,?,?,?,?)',
                        (row['build_id'], json.loads(row['target'])['id'], row['seed'], str(source), row['id'],
                         row['status'], row['teacher'], hashlib.sha256((row['result'] or '').encode()).hexdigest()))
                for table in ('attempts', 'job_quarantines', 'job_scope_changes', 'jobs'):
                    new.execute('DELETE FROM ' + table)
                new.execute('''CREATE TABLE standalone_batch_origins(
                    job_id TEXT PRIMARY KEY,source_database TEXT NOT NULL,source_job_id TEXT NOT NULL,
                    source_attempts INTEGER NOT NULL,source_teacher TEXT NOT NULL,created_at REAL NOT NULL)''')
                stamp = time.time()
                for row in pending:
                    target = json.loads(row['target']); bid = row['build_id']
                    require(not new.execute('SELECT 1 FROM prior_collected_inputs WHERE build_id=? AND target_id=? AND seed=?',
                            (bid, target['id'], row['seed'])).fetchone(), 'Pending source input conflicts with preserved history')
                    jid = digest([bid, target['id'], row['seed'], teacher])
                    new.execute('INSERT INTO jobs(id,build_id,target,seed,teacher,created) VALUES(?,?,?,?,?,?)',
                                (jid, bid, row['target'], row['seed'], canonical(teacher), row['created']))
                    new.execute('INSERT INTO standalone_batch_origins VALUES(?,?,?,?,?,?)',
                                (jid, str(source), row['id'], row['attempts'], row['teacher'], stamp))
                report = dict(sourceDatabase=str(source), destinationDatabase=str(destination), beforeCounts=counts,
                              pendingMigrated=len(pending), previousTeacher=teachers[0], teacher=teacher,
                              acceptance=acceptance, completedResultsRelabelled=0, sourceModified=False,
                              scope='Only pending work copied to new teacher jobs; all native results and failed attempts stay in the source snapshot.')
                new.execute('INSERT INTO collection_settings VALUES(?,?)', ('standalone_handoff', canonical(report)))
            require(new.execute('SELECT count(*) FROM jobs').fetchone()[0] == len(pending), 'Pending migration count differs')
            require(new.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0, 'Old attempts leaked into new teacher jobs')
            require(new.execute('PRAGMA quick_check').fetchone()[0] == 'ok', 'Prepared queue failed integrity check')
            new.execute('PRAGMA journal_mode=DELETE')
            new.execute('VACUUM')
        finally:
            store.db.close()
    temporary.replace(destination)
    return report


def prepare_instance(folder, bundle, readiness, native, real_snapshot):
    """Stage private runtime/source files; the original active pointer is untouched."""
    from damage_model.source_backfill import historical_plan
    folder, bundle = Path(folder).resolve(), Path(bundle).resolve(strict=True)
    require(readiness.get('passed') is True and readiness.get('selectedWorkers') in (8, 16, 24, 32),
            'Instance requires accepted concurrency selection')
    checked_identity(readiness['releaseManifest'])
    require(readiness['releaseManifest'] == identity(bundle / 'release.json'), 'Accepted bundle differs')
    checked_identity(readiness['finalReport'])
    soak = read(readiness['finalReport']['path'])['soak']; checked_identity(soak)
    launch = Path(soak['path']).parent / 'launch.json'; calibrated = read(launch)
    cpus = calibrated['cpus']
    require(cpus and all(type(cpu) is int and cpu >= 0 for cpu in cpus)
            and len(set(cpus)) == len(cpus) >= readiness['selectedWorkers']
            and set(cpus) <= os.sched_getaffinity(0), 'Calibrated CPU affinity is unavailable')
    require(calibrated['command'][:3] == ['taskset', '-c', ','.join(map(str, cpus))],
            'Soak CPU binding differs from its actual launch command')
    calibration = dict(launch=identity(launch), cpus=cpus,
                       minimumCpuQuota=calibrated['resources']['cpuQuotaCores'])
    checked_identity(native['session']); checked_identity(native['activePointer'])
    old_session = read(native['session']['path'])
    metadata = Path(real_snapshot).resolve(strict=True).parent
    require(read(metadata / 'collection-session.json') == old_session, 'Backup session differs from paused native session')
    require(read(metadata / 'active-collection.json') == read(native['activePointer']['path']),
            'Backup active pointer differs from paused native pointer')
    start = old_session.get('source_start', old_session.get('historical_source_start'))
    require(start is not None and old_session.get('backfill_dir'), 'Expected live and historical source policy')
    plan = read(metadata / 'source-backfill/plan.json')
    require(plan['schema'] == 1 and plan['cutoff'] == start and plan['phases'] == historical_plan(start)
            and 0 <= plan['phase_index'] <= len(plan['phases']), 'Historical source scope differs')
    # Copy the metadata captured BEFORE the real database snapshot. A live cursor
    # read at handoff could be ahead of those rows and skip unimported input pages.
    source_files = {Path('spire-codex/cursor.json'): metadata / 'cursor.json'}
    for name in ('plan.json', 'export-rate.json', 'latest.json'):
        path = metadata / 'source-backfill' / name
        if path.exists(): source_files[Path('spire-codex-history') / name] = path
    for path in sorted((metadata / 'source-backfill').glob('*/cursor.json')):
        source_files[Path('spire-codex-history') / path.parent.name / path.name] = path
    for index, phase in enumerate(plan['phases']):
        if index < plan['phase_index']:
            require(read(metadata / 'source-backfill' / phase['name'] / 'cursor.json').get('complete') is True,
                    'Completed historical phase lost its cursor')
    payloads = {relative: path.read_bytes() for relative, path in source_files.items()}
    for payload in payloads.values(): json.loads(payload)
    instance = folder / 'instance'
    require(not instance.exists(), 'Preserve an existing instance preparation for diagnosis')
    instance.mkdir()
    sources = {}
    for relative, payload in payloads.items():
        destination = instance / 'data/external' / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with destination.open('xb') as stream: stream.write(payload)
        sources[str(relative)] = dict(source=identity(source_files[relative]), destination=identity(destination))
    from run_standalone_rollout import make_runtimes
    runtimes = make_runtimes(bundle, instance, readiness['selectedWorkers'])
    paths = {name: str(folder / (name + '.sqlite')) for name in ('real', 'mutation', 'targeted')}
    session = dict(state='prepared', productionDeployed=False, project=str(instance),
        source_project=old_session['project'], active_db=paths['real'], mutation_db=paths['mutation'],
        targeted_db=paths['targeted'], teacher=str(bundle / 'teacher.json'),
        config=str(bundle / 'configs/real-runs-8s.json'),
        mutation_policy=str(bundle / 'configs/mutations-8s.json'),
        targeted_policy=str(bundle / 'configs/mutations-targeted-8s.json'),
        source_dir=str(instance / 'data/external/spire-codex'), source_start=start,
        backfill_dir=str(instance / 'data/external/spire-codex-history'),
        runtimes=list(map(str, runtimes)), workers=len(runtimes), selected_workers=len(runtimes),
        reserve_gib=16, worker_start_gib=2, collect_only=True, cpu_calibration=calibration,
        dataset_allocation=dict(real=0.5, mutation=0.25, targeted=0.25),
        controller_pid=None, pool_pid=None, releaseManifest=readiness['releaseManifest'],
        acceptance=identity(folder / 'readiness.json'), nativeSession=native['session'],
        originalActivePointer=native['activePointer'], backup_interval_seconds=1800)
    write(instance / 'data/collection-session.json', session)
    pointer = dict(active_db=paths['real'], mutation_db=paths['mutation'], targeted_db=paths['targeted'],
                   session=str(instance / 'data/collection-session.json'),
                   releaseManifest=readiness['releaseManifest'], acceptance=session['acceptance'])
    write(instance / 'data/active-collection.json', pointer)
    command = ['taskset', '-c', ','.join(map(str, cpus)), sys.executable, str(bundle / 'release_tool.py'), 'run', '--bundle', str(bundle),
               '--module', 'tools.collect_continuous', '--', '--db', paths['real'],
               '--mutation-db', paths['mutation'], '--targeted-db', paths['targeted'],
               '--config', session['config'], '--teacher', session['teacher'],
               '--mutation-policy', session['mutation_policy'], '--targeted-policy', session['targeted_policy'],
               '--source-dir', session['source_dir'], '--source-start', start,
               '--backfill-dir', session['backfill_dir'], '--active-pointer', native['activePointer']['path'],
               '--runtimes', *session['runtimes'], '--reserve-gib', '16', '--worker-start-gib', '2', '--collect-only']
    result = dict(directory=str(instance), sources=sources, calibration=calibration,
        runtimes=[identity(path) for path in runtimes], session=identity(instance / 'data/collection-session.json'),
        proposedPointer=identity(instance / 'data/active-collection.json'),
        originalActivePointer=native['activePointer'], command=command, cwd=str(instance),
        productionDeployed=False,
        remaining='Recheck ownership and immutable acceptance; activate pointers, start collector with backups/native audit/resource monitoring, and verify actual outputs.')
    write(instance / 'preparation.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('rollout', 'native-backup-report', 'directory'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    require(not args.directory.exists(), 'Use a new handoff preparation directory')
    readiness = verify_acceptance(args.rollout)
    plan = read(args.rollout / 'plan.json'); bundle = Path(plan['bundle'])
    native = read(args.native_backup_report)
    require(native.get('passed') is True and len(native['databases']) == 3, 'Complete three-queue native rollback backup required')
    checked_identity(native['session']); checked_identity(native['activePointer'])
    session = read(native['session']['path']); project = Path(session['project'])
    for name in ('configs/real-runs-8s.json', 'configs/mutations-8s.json',
                 'configs/mutations-targeted-8s.json', 'catalogs/game-0.111.0.raw.json'):
        require(read(project / name) == read(bundle / name), 'Formal input policy changed: ' + name)
    sources = {entry['database']: entry for entry in native['databases']}
    queues = {}
    for name, key in (('real', 'active_db'), ('mutation', 'mutation_db'), ('targeted', 'targeted_db')):
        source = (project / session[key]).resolve()
        entry = sources[str(source)]
        require(entry['restoration']['passed'] is True, 'Native rollback restoration did not pass')
        snapshot = Path(entry['backup']['directory']) / source.name
        checked_identity({'path': str(snapshot.resolve()), 'sha256': entry['backup']['manifest']['sha256']})
        queues[name] = snapshot
    # Use the exact accepted schema/Store implementation when preparing real queues.
    sys.path.insert(0, str(bundle))
    from damage_model.catalog import Catalog
    catalog = Catalog.load(bundle / 'catalogs/game-0.111.0.raw.json', bundle / 'configs/real-runs-8s.json')
    teacher = read(bundle / 'teacher.json')
    folder = args.directory.resolve(); folder.mkdir(parents=True)
    write(folder / 'readiness.json', readiness)
    reports = {}
    for name, source in queues.items():
        reports[name] = migrate_queue(source, folder / (name + '.sqlite'), teacher, catalog, identity(folder / 'readiness.json'))
        write(folder / (name + '-migration.json'), reports[name])
    instance = prepare_instance(folder, bundle, readiness, native, queues['real'])
    write(folder / 'preparation.json', dict(prepared=True, productionDeployed=False, releaseManifest=plan['releaseManifest'],
          nativeBackup=identity(args.native_backup_report), readiness=identity(folder / 'readiness.json'),
          queues={name: identity(folder / (name + '.sqlite')) for name in queues}, reports=reports,
          instance=identity(Path(instance['directory']) / 'preparation.json'), remaining=instance['remaining']))
    print({name: report['pendingMigrated'] for name, report in reports.items()})


if __name__ == '__main__':
    main()
