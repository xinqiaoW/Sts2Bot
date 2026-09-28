"""Freeze and run a verified formal handoff; never change accepted game artifacts."""
import argparse
from contextlib import ExitStack, closing, contextmanager
import fcntl
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time

import psutil

from standalone_rollout_metrics import identity, read, resource_snapshot, write
from standalone_rollout_provenance import checked_identity, require


CONTROL = ('deploy_standalone.py', 'standalone_production_supervisor.py', 'standalone_production_guard.py',
           'standalone_rollout_metrics.py', 'standalone_rollout_provenance.py', 'run_standalone_rollout.py',
           'verify_standalone_acceptance.py')


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def compare_snapshot(source, snapshot):
    """Compare every table, including source history and mutation/sequence metadata."""
    source, snapshot = Path(source).resolve(strict=True), Path(snapshot).resolve(strict=True)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as old, \
         closing(sqlite3.connect(snapshot.as_uri() + '?mode=ro', uri=True)) as saved:
        versions = [db.execute('PRAGMA data_version').fetchone()[0] for db in (old, saved)]
        for db in (old, saved): db.execute('BEGIN')
        schema = "SELECT type,name,tbl_name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY type,name"
        require(old.execute(schema).fetchall() == saved.execute(schema).fetchall(), 'Native schema changed since rollback backup')
        tables = old.execute("SELECT name,sql FROM sqlite_schema WHERE type='table' ORDER BY name").fetchall()
        checked = {}
        for name, ddl in tables:
            # SQLite backup preserves rowids. Read in physical row order rather
            # than performing millions of random secondary-index page lookups.
            columns = old.execute('PRAGMA table_info(' + quote(name) + ')').fetchall()
            primary = [r[1] for r in sorted(columns, key=lambda r: r[5]) if r[5]]
            without_rowid = 'WITHOUT ROWID' in ' '.join((ddl or '').upper().split())
            order = ','.join(map(quote, primary)) if without_rowid else 'rowid'
            selection = '*' if without_rowid else 'rowid,*'
            sql = 'SELECT ' + selection + ' FROM ' + quote(name) + ' ORDER BY ' + order
            left, right = old.execute(sql), saved.execute(sql)
            total = 0
            while True:
                a, b = left.fetchmany(128), right.fetchmany(128)
                require(a == b, 'Native rows changed since rollback backup: ' + name)
                total += len(a)
                if not a: break
            checked[name] = total
        for db in (old, saved): db.rollback()
        require(versions == [db.execute('PRAGMA data_version').fetchone()[0] for db in (old, saved)],
                'A native database changed during handoff verification')
    return dict(passed=True, source=str(source), snapshot=str(snapshot), tables=checked)


@contextmanager
def native_ownership(native):
    checked_identity(native['session']); checked_identity(native['activePointer'])
    session = read(native['session']['path']); project = Path(session['project'])
    require(session.get('state') == 'paused', 'Original native collection must remain paused')
    paths = [(project / session[key]).resolve(strict=True) for key in ('active_db', 'mutation_db', 'targeted_db')]
    require(len(set(paths)) == 3, 'Original native queues overlap')
    real = next(entry for entry in native['databases'] if entry['database'] == str(paths[0]))
    metadata = Path(real['backup']['directory'])
    runtimes_saved = read(metadata / 'runtime-configs/manifest.json')
    require({str(Path(entry['source']).resolve()) for entry in runtimes_saved}
            == {str(Path(path).resolve()) for path in session['runtimes']}, 'Original runtime set differs')
    for entry in runtimes_saved:
        require(identity(entry['source'])['sha256'] == identity(metadata / entry['backup'])['sha256'] == entry['sha256'],
                'Original runtime configuration changed since rollback backup')
    runtimes = [read(path) for path in session['runtimes']]
    lock_paths = [paths[0].with_suffix('.continuous.lock'), *[p.with_suffix('.pool.lock') for p in paths],
                  *[Path(runtime['data_dir']) / 'collector.lock' for runtime in runtimes]]
    with ExitStack() as stack:
        for path in lock_paths:
            lock = stack.enter_context(path.open('r'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for path in paths:
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                require(db.execute("SELECT count(*) FROM jobs WHERE status='running'").fetchone()[0] == 0,
                        'Original native queue still has running leases')
        checked_identity(native['session']); checked_identity(native['activePointer'])
        yield session, paths, runtimes


def activate_pointer(instance, native, directory, rollback_check, readiness):
    """Journal the two-file handoff. Publish the active pointer only after session writes."""
    directory = Path(directory)
    journal = directory / 'handoff-journal.json'
    require(not journal.exists(), 'Existing handoff journal requires diagnosis')
    checked_identity(native['session']); checked_identity(native['activePointer'])
    checked_identity(instance['session']); checked_identity(instance['proposedPointer'])
    checked_identity(rollback_check); require(read(rollback_check['path'])['passed'], 'Native rollback recheck failed')
    checked_identity(readiness)
    originals = {}
    for key in ('session', 'activePointer'):
        target = directory / ('native-' + key + '.before.json')
        with target.open('xb') as stream:
            stream.write(Path(native[key]['path']).read_bytes()); stream.flush(); os.fsync(stream.fileno())
        originals[key] = identity(target)
    receipt = dict(state='switching', activated=False, nativeOriginals=originals, readiness=readiness,
                   rollbackCheck=rollback_check, proposedPointer=instance['proposedPointer'], updated=time.time())
    write(journal, receipt)
    try:
        session = read(instance['session']['path'])
        session.update(state='starting', productionDeployed=False, supervisor_pid=os.getpid(),
                       supervisor_created=psutil.Process().create_time(),
                       supervisor_status=str(directory / 'supervisor/status.json'),
                       operational_role='formal-collection', deployment=str(directory / 'plan.json'))
        write(instance['session']['path'], session)
        write(native['session']['path'], session)
        write(native['activePointer']['path'], read(instance['proposedPointer']['path']))
        receipt.update(state='activated', activated=True, activePointer=identity(native['activePointer']['path']),
                       nativeSession=identity(native['session']['path']), updated=time.time())
        write(journal, receipt)
        return receipt
    except BaseException as error:
        receipt.update(state='failed', error=repr(error), updated=time.time())
        write(journal, receipt)
        raise


def prepare(handoff, audit, directory):
    handoff, audit = Path(handoff).resolve(strict=True), Path(audit).resolve(strict=True)
    directory = Path(directory).resolve()
    require(not directory.exists(), 'Use a new deployment directory')
    prep = read(handoff / 'preparation.json')
    require(prep.get('prepared') is True, 'Handoff queues are not prepared')
    for entry in [prep['instance'], prep['readiness'], prep['nativeBackup'], prep['releaseManifest'], *prep['queues'].values()]:
        checked_identity(entry)
    instance = read(prep['instance']['path'])
    for entry in [instance['session'], instance['proposedPointer'], instance['calibration']['launch'],
                  *instance['runtimes'], *[v['destination'] for v in instance['sources'].values()]]:
        checked_identity(entry)
    ready = read(prep['readiness']['path']); native = read(prep['nativeBackup']['path'])
    require(ready.get('passed') is True and ready['releaseManifest'] == prep['releaseManifest'], 'Accepted release differs')
    checked_identity(ready['finalReport'])
    require(native.get('passed') is True and len(native['databases']) == 3, 'Three native rollback snapshots required')
    checked_identity(native['session']); checked_identity(native['activePointer'])
    audit_prep = read(audit / 'preparation.json'); checked_identity(audit_prep['plan'])
    audit_plan = read(audit_prep['plan']['path'])
    require(audit_plan['handoffPreparation'] == identity(handoff / 'preparation.json')
            and audit_plan['instancePreparation'] == prep['instance'], 'Native auditor is bound to another handoff')
    metadata = {}
    for entry in native['databases']:
        snapshot = Path(entry['backup']['directory']) / Path(entry['database']).name
        checked_identity({'path': str(snapshot.resolve()), 'sha256': entry['backup']['manifest']['sha256']})
        require(entry['restoration']['passed'], 'Native rollback restoration did not pass')
        for path in snapshot.parent.rglob('*.json'): metadata[str(path.resolve())] = identity(path)
    directory.mkdir(parents=True)
    control = directory / 'control'; (control / 'tools').mkdir(parents=True)
    for name in CONTROL: shutil.copyfile(Path(__file__).parent / name, control / name)
    for name in ('local_backup.py', 'rental_backup.py'):
        shutil.copyfile(Path(__file__).parent / name, control / 'tools' / name)
    (control / 'tools/__init__.py').write_text('')
    files = {str(p.relative_to(control)): identity(p) for p in control.rglob('*.py')}
    write(directory / 'plan.json', dict(schema='standalone-formal-deployment/v1',
        handoff=identity(handoff / 'preparation.json'), auditPreparation=identity(audit / 'preparation.json'),
        nativeMetadata=metadata, control=files, productionDeployed=False))
    command = [sys.executable, str(control / 'deploy_standalone.py'), 'run', '--directory', str(directory)]
    write(directory / 'preparation.json', dict(plan=identity(directory / 'plan.json'), command=command,
        productionDeployed=False, scope='Verified deployment preparation; no pointers changed or processes started.'))
    return command


def run(directory):
    directory = Path(directory).resolve(strict=True)
    preparation = read(directory / 'preparation.json'); checked_identity(preparation['plan'])
    require(preparation['plan'] == identity(directory / 'plan.json'), 'Deployment preparation points elsewhere')
    plan = read(directory / 'plan.json')
    require(plan.get('schema') == 'standalone-formal-deployment/v1', 'Expected frozen formal deployment plan')
    expected_files = {*CONTROL, 'tools/__init__.py', 'tools/local_backup.py', 'tools/rental_backup.py'}
    require(set(plan['control']) == expected_files, 'Deployment control code set differs')
    for name, entry in plan['control'].items():
        require(entry == identity(Path(__file__).parent / name), 'Deployment control changed: ' + name)
    for entry in [plan['handoff'], plan['auditPreparation'], *plan['nativeMetadata'].values()]: checked_identity(entry)
    prep = read(plan['handoff']['path'])
    for entry in [prep['instance'], prep['readiness'], prep['nativeBackup'], prep['releaseManifest'], *prep['queues'].values()]:
        checked_identity(entry)
    instance, native = read(prep['instance']['path']), read(prep['nativeBackup']['path'])
    bundle = Path(prep['releaseManifest']['path']).parent
    sys.path.insert(1, str(bundle))
    from damage_model.provenance import verify_runtime
    from tools.local_backup import backup_once
    require(Path(sys.modules[verify_runtime.__module__].__file__).resolve() == bundle / 'damage_model/provenance.py',
            'Runtime verifier did not load from accepted bundle')
    require(Path(sys.modules[backup_once.__module__].__file__).resolve() == Path(__file__).parent / 'tools/local_backup.py',
            'Backup implementation did not load from frozen deployment')
    from standalone_production_supervisor import supervise
    from standalone_production_guard import drain_spec, drain_state
    affinity = os.sched_getaffinity(0); calibration = instance['calibration']
    checked_identity(calibration['launch'])
    require(set(calibration['cpus']) <= affinity, 'Calibrated CPUs no longer available')
    require(resource_snapshot()['cpuQuotaCores'] >= calibration['minimumCpuQuota'], 'CPU quota below accepted calibration')
    require(instance['command'][:3] == ['taskset', '-c', ','.join(map(str, calibration['cpus']))], 'Collector CPU binding differs')
    with (directory / 'deployment.lock').open('a+') as deployment_lock:
        fcntl.flock(deployment_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        require(not (directory / 'run-started.json').exists(), 'Previous deployment attempt requires diagnosis')
        write(directory / 'run-started.json', dict(pid=os.getpid(), created=psutil.Process().create_time(), plan=identity(directory / 'plan.json')))
        with native_ownership(native) as (old_session, old_paths, old_runtimes):
            for runtime in old_runtimes: verify_runtime(runtime, old_session['teacher'])
            saved_by_path = {entry['database']: entry for entry in native['databases']}
            checks = []
            for path in old_paths:
                write(directory / 'status.json', dict(state='verifying_native_snapshot', database=str(path), checked=checks))
                entry = saved_by_path[str(path)]; snapshot = Path(entry['backup']['directory']) / path.name
                checked_identity({'path': str(snapshot.resolve()), 'sha256': entry['backup']['manifest']['sha256']})
                checks.append(compare_snapshot(path, snapshot))
            write(directory / 'native-recheck.json', dict(passed=True, databases=checks))
            for entry in [instance['session'], instance['proposedPointer'], *instance['runtimes'],
                          *[v['destination'] for v in instance['sources'].values()]]: checked_identity(entry)
            spec = drain_spec(instance); require(drain_state(spec)['drained'], 'Prepared instance is owned')
            cwd = Path.cwd(); activation = None
            def activate():
                nonlocal activation
                for entry in [prep['instance'], prep['readiness'], prep['releaseManifest']]: checked_identity(entry)
                activation = activate_pointer(instance, native, directory, identity(directory / 'native-recheck.json'), prep['readiness'])
                return activation
            def backup():
                return {name: backup_once(Path(prep['queues'][name]['path']), directory / 'backups' / name,
                                         directory / (name + '-backup.json')) for name in ('real', 'mutation', 'targeted')}
            def started(controller):
                checked_identity(activation['activePointer']); checked_identity(activation['nativeSession'])
                live = read(instance['session']['path'])
                live.update(state='collecting', productionDeployed=True, controller_pid=controller.pid,
                            controller_created=psutil.Process(controller.pid).create_time())
                write(instance['session']['path'], live); write(native['session']['path'], live)
            try:
                os.sched_setaffinity(0, calibration['cpus']); os.chdir(instance['cwd'])
                write(directory / 'status.json', dict(state='supervising', updated=time.time(),
                      supervisorStatus=str(directory / 'supervisor/status.json')))
                supervise(instance, Path(plan['auditPreparation']['path']).parent, directory / 'supervisor',
                          activate=activate, backup=backup, started=started)
            finally:
                os.chdir(cwd); os.sched_setaffinity(0, affinity)
                if activation is not None:
                    live = read(instance['session']['path'])
                    state_file = directory / 'supervisor/status.json'
                    state = read(state_file) if state_file.exists() else {'state': 'failed'}
                    live.update(state=state['state'], controller_pid=state.get('controllerPid'), productionDeployed=True)
                    write(instance['session']['path'], live)
                    if identity(native['activePointer']['path']) == activation['activePointer']:
                        write(native['session']['path'], live)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    preparation = sub.add_parser('prepare')
    for name in ('handoff', 'audit', 'directory'): preparation.add_argument('--' + name, type=Path, required=True)
    launch = sub.add_parser('run'); launch.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare': print(json.dumps(prepare(args.handoff, args.audit, args.directory)))
    else:
        try:
            run(args.directory)
        except BaseException as error:
            if (args.directory / 'run-started.json').exists():
                write(args.directory / 'status.json', dict(state='failed', error=repr(error), updated=time.time(),
                      supervisorStatus=str(args.directory / 'supervisor/status.json')))
            raise
