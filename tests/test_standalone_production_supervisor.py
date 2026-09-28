"""Real processes, SQLite and backups around synthetic deployment/audit prerequisites."""
import json
from pathlib import Path
import sqlite3
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import standalone_production_supervisor as supervisor
from standalone_rollout_metrics import identity, read, write
from tools.local_backup import backup_once


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    root = tmp_path / 'handoff'; instance = root / 'instance'; instance.mkdir(parents=True)
    directory = root / 'supervisor'; audit = root / 'audit'; audit.mkdir()
    queues = {name: root / (name + '.sqlite') for name in ('real', 'mutation', 'targeted')}
    for path in queues.values():
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE jobs(status TEXT)'); db.execute("INSERT INTO jobs VALUES('pending')")
    worker = instance / 'workers/00'; worker.mkdir(parents=True)
    runtime = instance / 'runtime.json'; write(runtime, {'data_dir': str(worker)})
    session = instance / 'data/collection-session.json'
    write(session, dict(active_db=str(queues['real']), mutation_db=str(queues['mutation']),
                       targeted_db=str(queues['targeted']), workers=1, runtimes=[str(runtime)]))
    proposed = instance / 'data/active-collection.json'; write(proposed, {'active_db': str(queues['real'])})
    global_pointer = tmp_path / 'native-active.json'; write(global_pointer, {'active_db': 'paused-native.sqlite'})
    controller = tmp_path / 'synthetic_controller.py'
    controller.write_text('''import fcntl,json,signal,sqlite3,sys,time
from pathlib import Path
directory=Path(sys.argv[1]); instance=Path(sys.argv[2]); mode=sys.argv[3]; active=Path(sys.argv[4])
spec=json.loads((directory/'drain-spec.json').read_text())
locks=[open(p,'a+') for p in spec['lockPaths']]
for lock in locks: fcntl.flock(lock,fcntl.LOCK_EX)
signal.signal(signal.SIGTERM,lambda *a:None)
db=sqlite3.connect(spec['queues'][0]);db.execute("UPDATE jobs SET status='running'");db.commit()
(instance/'collector-started').touch()
if mode=='normal': (directory/'STOP').touch()
if mode=='pointer': active.write_text('{"active_db":"changed.sqlite"}')
while not Path(spec['workerStops'][0]).exists(): time.sleep(.01)
db.execute("UPDATE jobs SET status='complete'");db.commit();db.close()
for lock in locks: lock.close()
(instance/'collector-exited').touch()
''')
    auditor = tmp_path / 'synthetic_auditor.py'
    auditor.write_text('''import hashlib,json,os,signal,sys,time
from pathlib import Path
folder=Path(sys.argv[1]);instance=Path(sys.argv[2]);mode=sys.argv[3]
p=folder/'plan.json'; plan={'path':str(p),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
ready={'ready':True,'pid':os.getpid(),'productionAudit':True,'plan':plan}
temporary=folder/'ready.tmp';temporary.write_text(json.dumps(ready));temporary.replace(folder/'audit-ready.json')
signal.signal(signal.SIGTERM,lambda *a:sys.exit(0))
while True:
 if mode=='audit' and (instance/'collector-started').exists():
  (folder/'audit-stop.json').write_text('{"error":"synthetic state mismatch"}');sys.exit(2)
 if (folder/'collection-drained.json').exists():
  (folder/'audit-report.json').write_text('{"passed":true}');break
 time.sleep(.01)
''')
    # Hardware is synthetic here; process ownership, locks and actual SQLite
    # backup contents below are exercised without depending on shared host load.
    monkeypatch.setattr(supervisor, 'resource_snapshot', lambda: dict(time=1, availableBytes=64*2**30,
        cpuQuotaCores=32, cgroups=[{'path': '/test', 'memory.events': 'oom_kill 0'}]))
    monkeypatch.setattr(supervisor.shutil, 'disk_usage', lambda p: SimpleNamespace(free=100*2**30))
    monkeypatch.chdir(instance)
    calls = []

    def make(mode):
        prepared = dict(directory=str(instance), cwd=str(instance), session=identity(session),
            runtimes=[identity(runtime)], proposedPointer=identity(proposed),
            command=[sys.executable, str(controller), str(directory), str(instance), mode, str(global_pointer)])
        write(instance / 'preparation.json', prepared)
        write(audit / 'plan.json', {'instancePreparation': identity(instance / 'preparation.json')})
        write(audit / 'preparation.json', dict(plan=identity(audit / 'plan.json'),
              command=[sys.executable, str(auditor), str(audit), str(instance), mode]))
        def activate():
            assert read(audit / 'audit-ready.json')['ready']
            assert read(directory / 'watchdog-ready.json')['ready']
            assert calls == ['backup']  # all prerequisites precede pointer handoff
            calls.append('activate')
            global_pointer.write_bytes(proposed.read_bytes())
            return dict(activated=True, activePointer=identity(global_pointer))
        def backup():
            calls.append('backup')
            if mode == 'backup' and 'activate' in calls: raise OSError('synthetic backup write failure')
            if mode == 'initial_backup': raise OSError('synthetic initial backup failure')
            return {name: backup_once(path, directory / 'backups' / name, directory / (name + '-backup.json'))
                    for name, path in queues.items()}
        return prepared, activate, backup
    return SimpleNamespace(make=make, directory=directory, audit=audit, instance=instance,
                           queues=queues, pointer=global_pointer, calls=calls)


def run(deployment, mode):
    prepared, activate, backup = deployment.make(mode)
    return supervisor.supervise(prepared, deployment.audit, deployment.directory,
        activate=activate, backup=backup, interval=.025, backup_interval=.25, drain_timeout=5)


def test_normal_stop_drains_audit_and_takes_a_final_real_backup(deployment):
    result = run(deployment, 'normal')
    assert result['state'] == 'paused' and result['drain']['drained']
    assert deployment.calls[:2] == ['backup', 'activate'] and deployment.calls[-1] == 'backup'
    assert (deployment.instance / 'collector-exited').exists()
    assert read(deployment.audit / 'audit-report.json')['passed']
    saved = read(deployment.directory / 'latest-backups.json')['real']
    with sqlite3.connect(Path(saved['directory']) / 'real.sqlite') as db:
        assert db.execute('SELECT status FROM jobs').fetchone()[0] == 'complete'
    assert read(deployment.directory / 'watchdog-stopped.json')['parent'] > 0


@pytest.mark.parametrize('mode,reason', [('audit','Native audit'), ('backup','backup write failure'), ('pointer','Frozen evidence changed')])
def test_failure_stops_real_controller_and_preserves_evidence(deployment, mode, reason):
    with pytest.raises((ValueError, OSError), match=reason): run(deployment, mode)
    result = read(deployment.directory / 'status.json')
    assert result['state'] == 'failed' and result['drain']['drained']
    assert (deployment.instance / 'collector-exited').exists()
    assert (deployment.directory / 'latest-backups.json').exists()
    with sqlite3.connect(deployment.queues['real']) as db:
        assert db.execute('SELECT status FROM jobs').fetchone()[0] == 'complete'
    assert (deployment.directory / 'audit.log').exists() and (deployment.directory / 'controller.log').exists()


def test_failed_initial_backup_never_activates_or_starts_collection(deployment):
    original = deployment.pointer.read_bytes()
    with pytest.raises(OSError, match='initial backup failure'): run(deployment, 'initial_backup')
    assert deployment.calls == ['backup'] and deployment.pointer.read_bytes() == original
    assert not (deployment.instance / 'collector-started').exists()
    assert read(deployment.directory / 'status.json')['productionDeployed'] is False


def test_stale_ready_file_is_not_a_live_audit_prerequisite(deployment):
    prepared, activate, backup = deployment.make('normal')
    write(deployment.audit / 'audit-ready.json', {'pid': 123, 'ready': True})
    with pytest.raises(ValueError, match='Audit already started'):
        supervisor.supervise(prepared, deployment.audit, deployment.directory, activate=activate, backup=backup)
    assert not deployment.directory.exists() and not deployment.calls


def test_started_session_publication_failure_drains_spawned_controller(deployment):
    prepared, activate, backup = deployment.make('publication')
    def fail(controller): raise OSError('synthetic owner publication failure')
    with pytest.raises(OSError, match='owner publication failure'):
        supervisor.supervise(prepared, deployment.audit, deployment.directory, activate=activate, backup=backup,
                             started=fail, interval=.025, drain_timeout=5)
    assert (deployment.directory / 'controller-owner.json').exists()
    result = read(deployment.directory / 'status.json')
    assert result['state'] == 'failed' and result['drain']['drained']
    with sqlite3.connect(deployment.queues['real']) as db:
        assert db.execute("SELECT count(*) FROM jobs WHERE status='running'").fetchone()[0] == 0
