"""Exercise real child ownership/locks without launching a game or collector."""
import json
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

import psutil
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from standalone_production_guard import drain_spec, drain_state, health_error, stop_and_drain
from standalone_rollout_metrics import identity, read, write
from test_standalone_handoff_instance import prepared
from prepare_standalone_handoff import prepare_instance


def test_drain_paths_remain_frozen_after_live_session_changes(prepared):
    folder = prepared[0]
    for name in ('real', 'mutation', 'targeted'):
        with sqlite3.connect(folder / (name + '.sqlite')) as db:
            db.execute('CREATE TABLE jobs(status TEXT)')
    instance = prepare_instance(*prepared)
    spec = drain_spec(instance)
    write(instance['session']['path'], {'state': 'changed after deployment'})
    assert len(spec['workerStops']) == 8 and len(spec['lockPaths']) == 12
    assert drain_state(spec)['drained']
    with pytest.raises(ValueError, match='Frozen evidence changed'): drain_spec(instance)


def test_even_rehashed_runtime_cannot_share_worker_directory(prepared):
    folder = prepared[0]
    for name in ('real', 'mutation', 'targeted'): (folder / (name + '.sqlite')).touch()
    instance = prepare_instance(*prepared)
    first, second = instance['runtimes'][:2]
    config = read(second['path']); config['data_dir'] = read(first['path'])['data_dir']; write(second['path'], config)
    instance['runtimes'][1] = identity(second['path'])
    with pytest.raises(ValueError, match='Worker directory or count differs'): drain_spec(instance)


@pytest.fixture
def spec(tmp_path):
    queues = []
    for name in ('real', 'mutation', 'targeted'):
        path = tmp_path / (name + '.sqlite')
        with sqlite3.connect(path) as db:
            db.execute('CREATE TABLE jobs(status TEXT)')
            db.execute("INSERT INTO jobs VALUES('pending')")
        queues.append(str(path))
    value = dict(queues=queues, controllerStop=str(tmp_path / 'real.continuous.stop'),
                 workerStops=[str(tmp_path / 'collector.stop')],
                 lockPaths=[str(tmp_path / 'real.continuous.lock'),
                            *[str(Path(p).with_suffix('.pool.lock')) for p in queues], str(tmp_path / 'collector.lock')])
    write(tmp_path / 'drain-spec.json', value)
    return value


def wait_until(condition):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if condition(): return
        time.sleep(.025)
    assert condition(), 'Synthetic child did not finish within test deadline'


def worker_script(tmp_path):
    script = tmp_path / 'worker.py'
    script.write_text('''import fcntl,json,sqlite3,time
from pathlib import Path
p=Path(__file__).parent
s=json.loads((p/'drain-spec.json').read_text())
locks=[open(s['lockPaths'][1],'a+'),open(s['lockPaths'][-1],'a+')]
for lock in locks: fcntl.flock(lock,fcntl.LOCK_EX)
db=sqlite3.connect(s['queues'][0]);db.execute("UPDATE jobs SET status='running'");db.commit()
(p/'worker-ready').touch()
while not Path(s['workerStops'][0]).exists(): time.sleep(.025)
time.sleep(.1)
db.execute("UPDATE jobs SET status='complete'");db.commit();db.close()
for lock in locks: lock.close()
(p/'worker-exited').touch()
''')
    return script


def test_controller_exit_does_not_claim_worker_already_drained(spec, tmp_path):
    worker = subprocess.Popen([sys.executable, str(worker_script(tmp_path))])
    controller = subprocess.Popen([sys.executable, '-c', 'pass']); controller.wait(timeout=5)
    try:
        wait_until(lambda: (tmp_path / 'worker-ready').exists())
        assert drain_state(spec)['drained'] is False
        result = stop_and_drain(spec, controller, tmp_path / 'drain.json', timeout=5)
        worker.wait(timeout=5)
        assert result['drained'] and result['controllerExited'] and not any(result['running'].values())
        assert (tmp_path / 'worker-exited').exists() and Path(spec['controllerStop']).exists()
        with sqlite3.connect(spec['queues'][0]) as db:
            assert db.execute('SELECT status FROM jobs').fetchone()[0] == 'complete'
    finally:
        if worker.poll() is None: worker.kill(); worker.wait(timeout=5)


def test_timeout_preserves_unfinished_lease_and_diagnostic(spec, tmp_path):
    with sqlite3.connect(spec['queues'][0]) as db: db.execute("UPDATE jobs SET status='running'")
    with pytest.raises(TimeoutError, match='preserve owners'):
        stop_and_drain(spec, None, tmp_path / 'drain.json', timeout=0)
    report = read(tmp_path / 'drain.json')
    assert report['drained'] is False and report['running'][spec['queues'][0]] == 1
    assert Path(spec['workerStops'][0]).exists()
    with sqlite3.connect(spec['queues'][0]) as db:
        assert db.execute('SELECT status FROM jobs').fetchone()[0] == 'running'


def test_supervisor_sigkill_still_stops_separately_sessioned_worker(spec, tmp_path):
    worker_script(tmp_path)
    parent_code = '''import json,os,subprocess,sys,time,psutil
from pathlib import Path
p=Path(__file__).parent
worker=subprocess.Popen([sys.executable,str(p/'worker.py')],start_new_session=True)
watch=subprocess.Popen([sys.executable,sys.argv[1],'--spec',str(p/'drain-spec.json'),
 '--parent',str(os.getpid()),'--parent-created',str(psutil.Process().create_time()),
 '--ready',str(p/'watchdog-ready.json')],start_new_session=True)
(p/'owners.json').write_text(json.dumps([{'pid':x.pid,'created':psutil.Process(x.pid).create_time()} for x in (worker,watch)]))
while not (p/'worker-ready').exists() or not (p/'watchdog-ready.json').exists(): time.sleep(.025)
(p/'parent-ready').touch()
while True: time.sleep(1)
'''
    script = tmp_path / 'parent.py'; script.write_text(parent_code)
    parent = subprocess.Popen([sys.executable, str(script), str(ROOT / 'tools/standalone_production_guard.py')])
    try:
        wait_until(lambda: (tmp_path / 'parent-ready').exists())
        parent.kill(); parent.wait(timeout=5)
        wait_until(lambda: (tmp_path / 'worker-exited').exists())
        assert read(tmp_path / 'watchdog-stopped.json')['signal'] == signal.SIGTERM
        assert drain_state(spec)['drained'] is True
        with sqlite3.connect(spec['queues'][0]) as db:
            assert db.execute('SELECT status FROM jobs').fetchone()[0] == 'complete'
    finally:
        if parent.poll() is None: parent.kill(); parent.wait(timeout=5)
        if (tmp_path / 'owners.json').exists():
            for owner in read(tmp_path / 'owners.json'):
                try:
                    process = psutil.Process(owner['pid'])
                    if process.create_time() == owner['created'] and process.status() != psutil.STATUS_ZOMBIE:
                        process.kill()
                except psutil.NoSuchProcess: pass


def test_watchdog_rejects_parent_identity_before_ready(spec, tmp_path):
    process = subprocess.run([sys.executable, str(ROOT / 'tools/standalone_production_guard.py'),
        '--spec', str(tmp_path / 'drain-spec.json'), '--parent', '0', '--parent-created', '0',
        '--ready', str(tmp_path / 'watchdog-ready.json')], timeout=5)
    assert process.returncode == 0 and not (tmp_path / 'watchdog-ready.json').exists()
    assert Path(spec['controllerStop']).exists() and Path(spec['workerStops'][0]).exists()


def test_shared_parent_oom_and_cpu_quota_loss_are_not_hidden_by_free_host_memory():
    before = dict(availableBytes=64 * 2**30, cpuQuotaCores=32,
                  cgroups=[dict(path='/account', **{'memory.events': 'oom_kill 1'})])
    args = dict(disk_free=100 * 2**30, counts={'complete': 1000}, audit_status={'counts': {'matched': 80}}, auditor_alive=True)
    assert health_error(before, before, **args) is None
    current = {**before, 'cgroups': [dict(path='/account', **{'memory.events': 'oom_kill 2'})]}
    assert 'OOM' in health_error(before, current, **args)
    assert 'CPU quota' in health_error(before, {**before, 'cpuQuotaCores': 16}, **args)
    assert 'hierarchy' in health_error(before, {**before, 'cgroups': []}, **args)
    assert 'memory reserve' in health_error(before, {**before, 'availableBytes': 15 * 2**30}, **args)
    assert 'disk reserve' in health_error(before, before, **{**args, 'disk_free': 49 * 2**30})
    assert 'backup failed' in health_error(before, before, **args, backup_error='disk write failed')
    assert 'audit process exited' in health_error(before, before, **{**args, 'auditor_alive': False})
    assert 'failed sample' in health_error(before, before, **{**args, 'audit_status': {'counts': {'native_failed': 1}}})
    assert 'failed jobs' in health_error(before, before, **{**args, 'counts': {'failed': 1}})
    assert health_error(before, before, **{**args, 'counts': {'complete': 990, 'quarantined': 10}}) is None
    assert 'quarantined' in health_error(before, before, **{**args, 'counts': {'complete': 990, 'quarantined': 11}})
