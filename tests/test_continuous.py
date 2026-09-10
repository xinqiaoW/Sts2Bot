"""Linux supervisor tests use isolated files and synthetic rows, never game workers."""
from argparse import Namespace
import json
from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip('fcntl')
from tools import collect_continuous as continuous


@pytest.fixture(autouse=True)
def isolated_source(monkeypatch):
    # Supervisor lifecycle tests neither download runs nor mutate source queues.
    monkeypatch.setattr(continuous.Controller, 'refill', lambda self: None)


def test_pool_adoption_and_duplicate_controller_are_exclusive(tmp_path):
    lock = tmp_path / 'pool.lock'
    with continuous.exclusive(lock) as held:
        assert held
        with continuous.exclusive(lock) as other:
            assert not other
        code = ('from tools.collect_continuous import exclusive; import sys\n'
                'with exclusive(sys.argv[1]) as held: sys.exit(8 if held else 0)')
        assert subprocess.run([sys.executable, '-c', code, str(lock)], timeout=10).returncode == 0
    with continuous.exclusive(lock) as held:
        assert held


@pytest.mark.parametrize('counts,state', [({'failed': 1}, 'complete'),
    ({'pending': 8}, 'failed'), ({'running': 1}, 'complete'), ({'complete': 6080}, 'training')])
def test_no_launch_or_train_after_unclean_exit(counts, state):
    with pytest.raises(ValueError):
        continuous.next_action(counts, state)


def test_bounded_pool_and_completed_panel_have_distinct_next_steps():
    assert continuous.next_action({'complete': 10, 'pending': 5}, 'batch_complete') == 'collect'
    assert continuous.next_action({'complete': 6080}, 'complete') == 'validate'
    assert continuous.checkpoint_directory(6080, 6080, 'first', 'later') == Path('first')
    assert continuous.checkpoint_directory(9000, 6080, 'first', 'later') == Path('later/samples-000009000')


def test_existing_pool_finishes_then_waits_for_real_source(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(continuous, 'available_gib', lambda: 96)
    controller = object.__new__(continuous.Controller)
    controller.args = Namespace(runtimes=['runtime.json'], reserve_gib=32, worker_start_gib=3, poll_seconds=1, stop_at=None, collect_only=False)
    controller.db_path = tmp_path / 'data.sqlite'
    controller.stop_path = tmp_path / 'stop'
    controller.stop_requested = False
    controller.child = None
    controller.configs = [{'data_dir': str(tmp_path)}]
    counts = {'complete': 4, 'pending': 2}
    controller.store = Namespace(counts=lambda: dict(counts))
    events = []
    controller.guard = lambda: None
    controller.status = lambda state, **details: events.append(state)
    controller.validate_or_train = lambda total: events.append(('validate', total))
    pool = controller.db_path.with_suffix('.pool.lock')
    adopted = continuous.exclusive(pool)
    assert adopted.__enter__()
    sleeps = []
    def sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 1:
            assert 'following_pool' in events and not any(isinstance(e, tuple) for e in events)
            counts.clear(); counts['complete'] = 6
            continuous.atomic_json(controller.db_path.with_suffix('.parallel.json'), {'state': 'complete'})
            adopted.__exit__(None, None, None)
        else:
            controller.stop_requested = True
    monkeypatch.setattr(continuous.time, 'sleep', sleep)
    def popen(command, **kwargs):
        pytest.fail('No source jobs: must not invent a new generation')
        assert '--train-after' not in command  # This controller owns subsequent training.
        events.append('launched')
        return Namespace(pid=123, poll=lambda: None)
    monkeypatch.setattr(continuous.subprocess, 'Popen', popen)
    controller.run()
    assert events.count('launched') == 0
    assert ('validate', 6) in events and 'waiting_source' in events
    assert events[-1] == 'paused'


def test_restart_reuses_complete_checkpoint_without_training(tmp_path, monkeypatch):
    pytest.importorskip('torch')
    from damage_model import checkpoint_validation
    controller = object.__new__(continuous.Controller)
    output = tmp_path / 'first'
    output.mkdir()
    (output / 'model.pt').write_bytes(b'synthetic artifact')
    (output / 'metrics.json').write_text('{}')
    controller.args = Namespace(initial_samples=6, initial_output=str(output), output_root=str(tmp_path / 'next'), collect_only=False)
    controller.progress = {'validated': []}
    controller.progress_path = tmp_path / 'progress.json'
    controller.store = controller.catalog = None
    controller.status = lambda *a, **k: None
    monkeypatch.setattr(checkpoint_validation, 'validate_checkpoint', lambda *a: {
        'model_sha256': 'model', 'job_ids_sha256': 'dataset', 'metrics': {}, 'baselines': {}})
    monkeypatch.setattr(continuous.subprocess, 'run', lambda *a, **k: pytest.fail('Duplicate training'))
    controller.validate_or_train(6)
    controller.validate_or_train(6)
    assert len(json.loads(controller.progress_path.read_text())['validated']) == 1
    (output / 'metrics.json').unlink()
    with pytest.raises(ValueError, match='Incomplete checkpoint'):
        controller.validate_or_train(6)


def test_memory_pause_cannot_hide_failed_jobs_or_orphaned_leases():
    reason = 'Insufficient available memory to add a worker'
    assert continuous.next_action({'pending': 4}, 'failed', reason) == 'collect'
    for counts in ({'pending': 4, 'failed': 1}, {'running': 1}):
        with pytest.raises(ValueError):
            continuous.next_action(counts, 'failed', reason)
    with pytest.raises(ValueError):
        continuous.next_action({'pending': 4}, 'draining', reason)


@pytest.mark.parametrize('owned', [False, True, 'stale-pid'])
@pytest.mark.parametrize('workers,reserve,budget,low,ready', [(8,32,3,15,90), (4,4,2,11.9,12), (4,0,2,7.9,8)])
def test_memory_pause_waits_and_resumes_once_without_changing_jobs(tmp_path, monkeypatch, owned, workers,reserve,budget,low,ready):
    monkeypatch.chdir(tmp_path)
    controller = object.__new__(continuous.Controller)
    controller.args = Namespace(runtimes=['runtime.json'] * workers, reserve_gib=reserve, worker_start_gib=budget, poll_seconds=1, stop_at=None, collect_only=False)
    controller.db_path = tmp_path / 'data.sqlite'
    controller.stop_path = tmp_path / 'stop'
    controller.stop_requested = False
    controller.child = Namespace(pid=9, poll=lambda: 1, wait=lambda: 1) if owned else None
    controller.configs = [{'data_dir': str(tmp_path)}]
    counts = {'complete': 7, 'pending': 4}
    controller.store = Namespace(counts=lambda: dict(counts))
    controller.guard = lambda: None
    events = []
    controller.status = lambda state, **details: events.append((state, details))
    continuous.atomic_json(controller.db_path.with_suffix('.parallel.json'), {
        'state': 'failed', 'pid': 10 if owned == 'stale-pid' else 9,
        'error': 'Insufficient available memory to add a worker'})
    memory = [low]
    monkeypatch.setattr(continuous, 'available_gib', lambda: memory[0])
    def sleep(seconds):
        if memory[0] == low:
            assert events[-1][0] == 'waiting_memory'
            assert events[-1][1]['required_gib'] == reserve + workers * budget
            memory[0] = ready
        else:
            controller.stop_requested = True
    monkeypatch.setattr(continuous.time, 'sleep', sleep)
    def popen(command, **kwargs):
        assert memory[0] == ready and counts == {'complete': 7, 'pending': 4}
        assert command[command.index('--reserve-gib')+1] == str(reserve)
        assert command[command.index('--worker-start-gib')+1] == str(budget)
        events.append(('launched', {}))
        return Namespace(pid=11, poll=lambda: None)
    monkeypatch.setattr(continuous.subprocess, 'Popen', popen)
    if owned == 'stale-pid':
        with pytest.raises(RuntimeError, match='exited with code'):
            controller.run()
        assert not events
    else:
        controller.run()
        assert [name for name, _ in events].count('launched') == 1
        assert events[-1][0] == 'paused'


@pytest.mark.parametrize('reserve,budget', [(-1,2),(3.9,2),(4,1.9),(float('nan'),2),(4,float('inf'))])
def test_resource_override_keeps_finite_minimums(reserve,budget):
    with pytest.raises(ValueError):
        continuous.validate_memory_bounds(reserve,budget)


def test_zero_reserve_keeps_running_worker_below_startup_budget(tmp_path, monkeypatch):
    from tools import collect_parallel as parallel
    from damage_model.store import Store
    monkeypatch.chdir(tmp_path)
    database = tmp_path / 'queue.sqlite'
    store = Store(database)
    with store.db:
        store.db.execute("INSERT INTO jobs(id,status,created) VALUES('pending-job','pending',1)")
    store.db.close()
    runtime = tmp_path / 'runtime.json'
    runtime.write_text(json.dumps({'data_dir':str(tmp_path), 'env':{'WINEPREFIX':str(tmp_path / 'prefix')}}))
    memory = [2.0]
    child = Namespace(pid=123, returncode=None)
    child.poll = lambda: child.returncode
    monkeypatch.setattr(parallel, 'available_gib', lambda: memory[0])
    monkeypatch.setattr(parallel.subprocess, 'Popen', lambda *a, **k: child)
    monkeypatch.setattr(parallel.signal, 'signal', lambda *a: None)
    states = []
    def sleep(seconds):
        state = json.loads(database.with_suffix('.parallel.json').read_text())
        states.append(state['state'])
        if seconds == 2:
            memory[0] = 0.5
        else:
            assert state['state'] == 'collecting' and state['available_gib'] == 0.5
            child.returncode = 0
    monkeypatch.setattr(parallel.time, 'sleep', sleep)
    monkeypatch.setattr(sys, 'argv', ['collect_parallel', '--db', str(database), '--runtimes', str(runtime),
        '--reserve-gib', '0', '--worker-start-gib', '2'])
    parallel.main()
    state = json.loads(database.with_suffix('.parallel.json').read_text())
    assert states == ['starting', 'collecting']
    assert state['state'] == 'batch_complete' and state['counts'] == {'pending': 1}
    assert not (tmp_path / 'collector.stop').exists()


def test_collection_only_records_panel_without_training_or_checkpoint_mutation(tmp_path, monkeypatch):
    controller = object.__new__(continuous.Controller)
    controller.args = Namespace(collect_only=True)
    first = {'completed_samples': 6080, 'model_sha256': 'original'}
    controller.progress = {'validated': [first]}
    controller.progress_path = tmp_path / 'progress.json'
    controller.status = lambda *a, **k: None
    monkeypatch.setattr(continuous.subprocess, 'run', lambda *a, **k: pytest.fail('Training on rental'))
    controller.validate_or_train(26368)
    controller.validate_or_train(26368)
    assert controller.progress['validated'] == [first]
    assert len(controller.progress['collected']) == 1
    assert controller.progress['collected'][0]['training_deferred'] is True


def test_deadline_drains_adopted_pool_without_launch_or_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    controller = object.__new__(continuous.Controller)
    controller.args = Namespace(stop_at=100)
    controller.configs = [{'data_dir': str(tmp_path)}]
    states = []
    controller.status = lambda state, **details: states.append(state)
    monkeypatch.setattr(continuous.time, 'time', lambda: 101)
    monkeypatch.setattr(continuous.subprocess, 'Popen', lambda *a, **k: pytest.fail('Launch after deadline'))
    controller.run()
    assert (tmp_path / 'collector.stop').exists()
    assert states == ['paused']


def test_rental_snapshot_contains_committed_data_and_valid_hash(tmp_path):
    import hashlib
    import sqlite3
    from tools.rental_backup import snapshot
    database = tmp_path / 'source.sqlite'
    db = sqlite3.connect(database)
    try:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE jobs(id TEXT, status TEXT)')
        db.executemany('INSERT INTO jobs VALUES(?,?)', [('a','complete'),('b','pending')])
        db.commit()
        db.execute('INSERT INTO jobs VALUES("not-committed", "complete")')
        output = tmp_path / 'upload'
        manifest = snapshot(database, output)
    finally:
        db.close()
    assert manifest['counts'] == {'complete': 1, 'pending': 1}
    assert manifest['sha256'] == hashlib.sha256((output / manifest['database']).read_bytes()).hexdigest()
    with sqlite3.connect(output / manifest['database']) as backup:
        assert backup.execute('SELECT id FROM jobs WHERE status="complete"').fetchone()[0] == 'a'


def test_expired_pool_preserves_pending_job_without_starting_game(tmp_path):
    from damage_model.store import Store
    database = tmp_path / 'queue.sqlite'
    store = Store(database)
    with store.db: store.db.execute("INSERT INTO jobs(id,status,created) VALUES('pending-job','pending',1)")
    store.db.close()
    config = tmp_path / 'runtime.json'
    config.write_text(json.dumps({'data_dir':str(tmp_path), 'env':{'WINEPREFIX':str(tmp_path / 'prefix')}}))
    result = subprocess.run([sys.executable, '-m', 'tools.collect_parallel', '--db', str(database),
        '--runtimes', str(config), '--reserve-gib', '4', '--stop-at', '1'], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    state = json.loads(database.with_suffix('.parallel.json').read_text())
    assert state['state'] == 'paused' and state['workers'] == 0
    assert state['counts'] == {'pending': 1}
