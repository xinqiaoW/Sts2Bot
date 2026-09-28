"""Synthetic handoff data exercises locks, complete snapshot comparison and journaling."""
import fcntl
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import deploy_standalone as deploy
from standalone_rollout_metrics import identity, read, write


@pytest.fixture
def native(tmp_path):
    project = tmp_path / 'native'; project.mkdir()
    runtime = project / 'runtime.json'; worker = project / 'worker'; worker.mkdir()
    write(runtime, {'data_dir': str(worker), 'backend': 'native-wine'})
    (worker / 'collector.lock').touch()
    entries = []
    for name in ('real', 'mutation', 'targeted'):
        source = project / (name + '.sqlite')
        with sqlite3.connect(source) as db:
            db.executescript('''CREATE TABLE jobs(id TEXT PRIMARY KEY,status TEXT,result TEXT);
                INSERT INTO jobs VALUES('pending','pending',NULL),('complete','complete','original native output');
                CREATE TABLE attempts(id INTEGER PRIMARY KEY AUTOINCREMENT,result BLOB);
                INSERT INTO attempts(result) VALUES(X'0012ff');
                CREATE TABLE collection_settings(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO collection_settings VALUES('mutation_sequence','17');
                CREATE TABLE source_runs(hash TEXT PRIMARY KEY,body TEXT);
                INSERT INTO source_runs VALUES('source','original source');
                CREATE TABLE lineage(a TEXT,b TEXT,PRIMARY KEY(a,b)) WITHOUT
                ROWID;
                INSERT INTO lineage VALUES('parent','child');''')
            target = tmp_path / 'backup' / name / source.name; target.parent.mkdir(parents=True)
            with sqlite3.connect(target) as saved: db.backup(saved)
        source.with_suffix('.pool.lock').touch()
        entries.append(dict(database=str(source), backup=dict(directory=str(target.parent),
                            manifest={'sha256': identity(target)['sha256']}), restoration={'passed': True}))
    (project / 'real.continuous.lock').touch()
    session = project / 'session.json'; pointer = project / 'active.json'
    write(session, dict(state='paused', project=str(project), active_db='real.sqlite', mutation_db='mutation.sqlite',
                        targeted_db='targeted.sqlite', runtimes=[str(runtime)]))
    write(pointer, {'active_db': str(project / 'real.sqlite')})
    metadata = Path(entries[0]['backup']['directory'])
    write(metadata / 'runtime-configs/00-runtime.json', read(runtime))
    write(metadata / 'runtime-configs/manifest.json', [dict(source=str(runtime), backup='runtime-configs/00-runtime.json',
                                                         sha256=identity(runtime)['sha256'])])
    return dict(passed=True, session=identity(session), activePointer=identity(pointer), databases=entries)


def test_all_native_tables_and_implicit_rowids_match_backup(native):
    entry = native['databases'][0]
    result = deploy.compare_snapshot(entry['database'], Path(entry['backup']['directory']) / 'real.sqlite')
    assert result['passed'] and result['tables'] == dict(attempts=1, collection_settings=1, jobs=2,
                                                       lineage=1, source_runs=1, sqlite_sequence=1)


@pytest.mark.parametrize('mutation', ['source', 'sequence', 'schema', 'attempt'])
def test_unchanged_job_counts_do_not_hide_changed_native_metadata(native, mutation):
    entry = native['databases'][0]
    with sqlite3.connect(entry['database']) as db:
        if mutation == 'source': db.execute("UPDATE source_runs SET body='later source page'")
        elif mutation == 'sequence': db.execute("UPDATE collection_settings SET value='18'")
        elif mutation == 'schema': db.execute('CREATE TABLE unexpected(x TEXT)')
        elif mutation == 'attempt': db.execute("UPDATE attempts SET result=X'00'")
    with pytest.raises(ValueError, match='changed since rollback backup'):
        deploy.compare_snapshot(entry['database'], Path(entry['backup']['directory']) / 'real.sqlite')


def test_native_locks_stay_owned_until_handoff_context_exits(native):
    source = Path(native['databases'][0]['database'])
    with deploy.native_ownership(native) as (_, paths, runtimes):
        assert source in paths and len(runtimes) == 1
        with source.with_suffix('.pool.lock').open('r') as other:
            with pytest.raises(BlockingIOError): fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with source.with_suffix('.pool.lock').open('r') as other:
        fcntl.flock(other, fcntl.LOCK_EX | fcntl.LOCK_NB)


@pytest.mark.parametrize('change', ['owned_pool', 'running', 'runtime'])
def test_active_or_changed_native_instance_rejects_ownership(native, change):
    source = Path(native['databases'][0]['database']); holder = None
    if change == 'owned_pool':
        holder = source.with_suffix('.pool.lock').open('r'); fcntl.flock(holder, fcntl.LOCK_EX | fcntl.LOCK_NB)
    elif change == 'running':
        with sqlite3.connect(source) as db: db.execute("UPDATE jobs SET status='running' WHERE id='pending'")
    elif change == 'runtime': write(source.parent / 'runtime.json', {'data_dir': '/unexpected'})
    try:
        with pytest.raises((BlockingIOError, ValueError)):
            with deploy.native_ownership(native): pytest.fail('Ownership should not be granted')
    finally:
        if holder: holder.close()


def activation_inputs(tmp_path):
    folder = tmp_path / 'deploy'; folder.mkdir()
    write(folder / 'instance/session.json', {'state': 'prepared', 'active_db': 'standalone.sqlite', 'teacher': 'frozen-teacher.json'})
    write(folder / 'instance/pointer.json', {'active_db': 'standalone.sqlite'})
    write(folder / 'native-recheck.json', {'passed': True})
    write(folder / 'readiness.json', {'passed': True})
    instance = dict(session=identity(folder / 'instance/session.json'), proposedPointer=identity(folder / 'instance/pointer.json'))
    return folder, instance, identity(folder / 'native-recheck.json'), identity(folder / 'readiness.json')


def test_active_pointer_is_published_after_both_sessions_and_keeps_native_bytes(native, tmp_path, monkeypatch):
    folder, instance, rollback, ready = activation_inputs(tmp_path)
    originals = {k: Path(native[k]['path']).read_bytes() for k in ('session', 'activePointer')}
    original_write = deploy.write; writes = []
    def track(path, value):
        writes.append(str(path)); original_write(path, value)
    monkeypatch.setattr(deploy, 'write', track)
    with deploy.native_ownership(native): result = deploy.activate_pointer(instance, native, folder, rollback, ready)
    assert result['activated'] and read(result['activePointer']['path']) == {'active_db': 'standalone.sqlite'}
    assert writes.index(instance['session']['path']) < writes.index(native['session']['path']) < writes.index(native['activePointer']['path'])
    for key, original in originals.items():
        assert Path(result['nativeOriginals'][key]['path']).read_bytes() == original
    assert read(native['session']['path'])['state'] == 'starting'
    with pytest.raises(ValueError, match='journal requires diagnosis'):
        deploy.activate_pointer(instance, native, folder, rollback, ready)


def test_interrupted_pointer_write_retains_original_pointer_and_partial_handoff_journal(native, tmp_path, monkeypatch):
    folder, instance, rollback, ready = activation_inputs(tmp_path)
    original_pointer = Path(native['activePointer']['path']).read_bytes(); original_write = deploy.write
    def fail(path, value):
        if str(path) == native['activePointer']['path']: raise OSError('synthetic pointer write failure')
        original_write(path, value)
    monkeypatch.setattr(deploy, 'write', fail)
    with deploy.native_ownership(native), pytest.raises(OSError, match='pointer write failure'):
        deploy.activate_pointer(instance, native, folder, rollback, ready)
    assert Path(native['activePointer']['path']).read_bytes() == original_pointer
    journal = read(folder / 'handoff-journal.json')
    assert journal['state'] == 'failed' and journal['activated'] is False
    assert read(native['session']['path'])['state'] == 'starting'
    assert read(journal['nativeOriginals']['session']['path'])['state'] == 'paused'


def test_changed_native_pointer_never_starts_handoff(native, tmp_path):
    folder, instance, rollback, ready = activation_inputs(tmp_path)
    write(native['activePointer']['path'], {'active_db': 'someone-else.sqlite'})
    with pytest.raises(ValueError, match='Frozen evidence changed'):
        deploy.activate_pointer(instance, native, folder, rollback, ready)
    assert not (folder / 'handoff-journal.json').exists()


def test_frozen_entrypoint_loads_and_rejects_changed_control_before_launch(native, tmp_path):
    # Minimal acceptance/queue receipts only exercise packaging. A real run
    # additionally requires the independently verified native auditor to be ready.
    handoff = tmp_path / 'prepared'; handoff.mkdir()
    bundle = tmp_path / 'bundle'; write(bundle / 'release.json', {'fixture': True})
    write(tmp_path / 'accepted-final.json', {'fixture': True})
    write(handoff / 'readiness.json', dict(passed=True, releaseManifest=identity(bundle / 'release.json'),
          finalReport=identity(tmp_path / 'accepted-final.json')))
    write(handoff / 'native-backup.json', native)
    write(handoff / 'instance/session.json', {'state': 'prepared'})
    write(handoff / 'instance/pointer.json', {'active_db': 'new.sqlite'})
    write(tmp_path / 'accepted-launch.json', {'fixture': True})
    instance = dict(session=identity(handoff / 'instance/session.json'), proposedPointer=identity(handoff / 'instance/pointer.json'),
                    calibration={'launch': identity(tmp_path / 'accepted-launch.json')}, runtimes=[], sources={})
    write(handoff / 'instance/preparation.json', instance)
    prep = dict(prepared=True, instance=identity(handoff / 'instance/preparation.json'),
                readiness=identity(handoff / 'readiness.json'), nativeBackup=identity(handoff / 'native-backup.json'),
                releaseManifest=identity(bundle / 'release.json'),
                queues={name: identity(entry['database']) for name, entry in zip(('real','mutation','targeted'), native['databases'])})
    write(handoff / 'preparation.json', prep)
    audit = tmp_path / 'audit'
    write(audit / 'plan.json', dict(handoffPreparation=identity(handoff / 'preparation.json'), instancePreparation=prep['instance']))
    write(audit / 'preparation.json', {'plan': identity(audit / 'plan.json')})
    destination = tmp_path / 'frozen-deployment'; command = deploy.prepare(handoff, audit, destination)
    help_result = subprocess.run(command[:2] + ['--help'], capture_output=True, text=True, timeout=5)
    assert help_result.returncode == 0 and 'prepare' in help_result.stdout
    assert (destination / 'control/tools/local_backup.py').read_bytes() == (ROOT / 'tools/local_backup.py').read_bytes()
    (destination / 'control/standalone_production_guard.py').write_text('changed control')
    rejected = subprocess.run(command, capture_output=True, text=True, timeout=5)
    assert rejected.returncode != 0 and 'Deployment control changed' in rejected.stderr
    assert not (destination / 'run-started.json').exists()
    assert read(native['session']['path'])['state'] == 'paused'
