import json
import sqlite3
from contextlib import nullcontext


def test_backup_releases_live_wal_before_verifying_copy(tmp_path, monkeypatch):
    from contextlib import contextmanager
    from tools import rental_backup
    path=tmp_path/'live.sqlite'
    writer=sqlite3.connect(path)
    writer.execute('PRAGMA journal_mode=WAL')
    writer.execute('PRAGMA wal_autocheckpoint=0')
    writer.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY,status TEXT)')
    writer.execute("INSERT INTO jobs VALUES(1,'complete')");writer.commit()
    @contextmanager
    def check_reader_released(_):
        writer.execute("INSERT INTO jobs VALUES(2,'complete')");writer.commit()
        # A pinned source snapshot prevents TRUNCATE from completing here.
        assert writer.execute('PRAGMA wal_checkpoint(TRUNCATE)').fetchone()[0]==0
        yield
    monkeypatch.setattr(rental_backup,'cached_snapshot_pages',check_reader_released)
    try:
        manifest=rental_backup.snapshot(path,tmp_path/'backup')
        assert manifest['counts']=={'complete':1}
        assert writer.execute('SELECT count(*) FROM jobs').fetchone()[0]==2
    finally:writer.close()
from pathlib import Path
from unittest.mock import patch

import pytest
pytest.importorskip('fcntl')

from tools.local_backup import backup_once, record_failure


def test_cached_verification_preserves_snapshot_bytes_with_wal_and_overflow_pages(tmp_path):
    from tools import rental_backup

    database = tmp_path / 'live.sqlite'
    writer = sqlite3.connect(database)
    try:
        writer.execute('PRAGMA journal_mode=WAL')
        writer.execute('CREATE TABLE jobs(id INTEGER PRIMARY KEY, status TEXT, payload BLOB)')
        writer.executemany('INSERT INTO jobs VALUES(?,?,?)', [
            (i, 'pending' if i % 10 == 0 else 'complete', bytes([i % 256]) * 65536)
            for i in range(200)
        ])
        writer.commit()
        with patch.object(rental_backup, 'cached_snapshot_pages', lambda path: nullcontext()):
            original = rental_backup.snapshot(database, tmp_path / 'original')
        cached = rental_backup.snapshot(database, tmp_path / 'cached')
        assert (tmp_path / 'cached' / database.name).read_bytes() == (tmp_path / 'original' / database.name).read_bytes()
        assert {k:v for k,v in cached.items() if k != 'created'} == {k:v for k,v in original.items() if k != 'created'}
        assert cached['counts'] == {'complete': 180, 'pending': 20}
    finally:
        writer.close()


def test_backup_captures_the_active_teacher_configuration(tmp_path, monkeypatch):
    from tools.local_backup import source_metadata
    monkeypatch.chdir(tmp_path)
    Path('data').mkdir(); Path('configs').mkdir()
    Path('configs/real-runs.json').write_text('{"short_search_budget_ms":2000}')
    Path('configs/real-runs-8s.json').write_text('{"short_search_budget_ms":8000}')
    Path('data/collection-session.json').write_text('{"config":"configs/real-runs-8s.json"}')
    captured=source_metadata('data/new.sqlite')
    assert json.loads(captured[Path('real-runs-8s.json')])['short_search_budget_ms']==8000
    Path('configs/real-runs-8s.json').unlink()
    with pytest.raises(FileNotFoundError): source_metadata('data/new.sqlite')


def test_backup_includes_targeted_selection_policy(tmp_path, monkeypatch):
    from tools.local_backup import source_metadata
    monkeypatch.chdir(tmp_path)
    Path('data').mkdir(); Path('configs').mkdir()
    Path('configs/targeted.json').write_text('{"target_selection":{"name":"balanced_error_targets_v1"}}')
    Path('data/collection-session.json').write_text('{"targeted_policy":"configs/targeted.json"}')
    assert json.loads(source_metadata('data/targeted.sqlite')[Path('targeted.json')])['target_selection']['name']=='balanced_error_targets_v1'


def test_two_slots_preserve_previous_consistent_database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = tmp_path / 'source.sqlite'
    connection = sqlite3.connect(db)
    connection.execute('create table jobs(status text)')
    connection.execute("insert into jobs values('complete')")
    connection.commit()
    state_path = tmp_path / 'state.json'
    first = backup_once(db, tmp_path / 'backups', state_path)
    connection.execute("insert into jobs values('complete')")
    connection.commit()
    second = backup_once(db, tmp_path / 'backups', state_path)
    assert first['slot'] != second['slot']
    for record, count in [(first, 1), (second, 2)]:
        with sqlite3.connect(Path(record['directory']) / db.name) as saved:
            assert saved.execute('select count(*) from jobs').fetchone()[0] == count
    assert json.loads(state_path.read_text()) == second
    connection.close()


def test_failure_keeps_last_success_pointer_and_snapshot(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = tmp_path / 'source.sqlite'
    with sqlite3.connect(db) as connection:
        connection.execute('create table jobs(status text)')
    state_path = tmp_path / 'state.json'
    first = backup_once(db, tmp_path / 'backups', state_path)
    with patch('tools.local_backup.snapshot', side_effect=RuntimeError('disk failure')):
        try:
            backup_once(db, tmp_path / 'backups', state_path)
        except RuntimeError as error:
            record_failure(state_path, error)
    assert json.loads(state_path.read_text())['last_success'] == first
    assert (Path(first['directory']) / db.name).exists()
    second = backup_once(db, tmp_path / 'backups', state_path)
    assert second['slot'] != first['slot'] and second['state'] == 'saved'


def test_backup_cursors_precede_snapshot_and_include_both_history_phases(tmp_path, monkeypatch):
    from tools import local_backup
    monkeypatch.chdir(tmp_path)
    db = tmp_path / 'source.sqlite'
    with sqlite3.connect(db) as connection:
        connection.execute('create table jobs(status text)')
    history = Path('data/external/history')
    for phase in ('recent-history', 'full-archive', 'compatible-archive-v1'):
        (history / phase).mkdir(parents=True)
        (history / phase / 'cursor.json').write_text('{"page_number":3}')
    (history / 'plan.json').write_text('{"phase_index":0}')
    (history / 'export-rate.json').write_text('{"next_request_at":1000}')
    Path('data/collection-session.json').write_text(json.dumps({'backfill_dir':str(history)}))
    live = Path('data/external/spire-codex/cursor.json')
    live.parent.mkdir(parents=True)
    live.write_text('{"page_number":88}')
    original_snapshot = local_backup.snapshot
    def advance_during_snapshot(*args):
        live.write_text('{"page_number":89}')
        (history / 'recent-history/cursor.json').write_text('{"page_number":4}')
        return original_snapshot(*args)
    monkeypatch.setattr(local_backup, 'snapshot', advance_during_snapshot)
    state = backup_once(db, tmp_path / 'backups', tmp_path / 'state.json')
    saved = Path(state['directory'])
    assert json.loads((saved / 'cursor.json').read_text()) == {'page_number':88}
    for phase in ('recent-history', 'full-archive', 'compatible-archive-v1'):
        assert json.loads((saved / 'source-backfill' / phase / 'cursor.json').read_text()) == {'page_number':3}
    assert (saved / 'source-backfill/plan.json').is_file()
    assert (saved / 'source-backfill/export-rate.json').is_file()


def test_snapshot_keeps_one_wal_snapshot_while_another_connection_commits(tmp_path, monkeypatch):
    from tools.rental_backup import snapshot

    database = tmp_path / 'live.sqlite'
    connect = sqlite3.connect
    writer = connect(database, timeout=1)
    writer.execute('PRAGMA journal_mode=WAL')
    writer.execute('CREATE TABLE jobs(status TEXT, payload BLOB)')
    writer.execute("INSERT INTO jobs VALUES('complete', zeroblob(65536))")
    writer.commit()
    writes = []

    class Source(sqlite3.Connection):
        def backup(self, destination, **kwargs):
            def progress(status, remaining, total):
                if remaining and not writes:
                    writer.execute("INSERT INTO jobs VALUES('complete', NULL)")
                    writer.commit()
                    writes.append(True)
            return super().backup(destination, pages=1, progress=progress)

    def connection(path, **kwargs):
        if kwargs.get('uri') and 'mode=ro' in str(path):
            kwargs['factory'] = Source
        return connect(path, **kwargs)

    monkeypatch.setattr(sqlite3, 'connect', connection)
    try:
        manifest = snapshot(database, tmp_path / 'backup')
        assert writes and writer.execute('SELECT count(*) FROM jobs').fetchone()[0] == 2
        assert manifest['counts'] == {'complete': 1}
        with connect(tmp_path / 'backup' / database.name) as backup:
            assert backup.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            assert backup.execute('SELECT count(*) FROM jobs').fetchone()[0] == 1
    finally:
        writer.close()


def test_backup_preserves_explicit_backend_teacher_and_rejects_missing_manifest(tmp_path, monkeypatch):
    from tools.local_backup import source_metadata
    monkeypatch.chdir(tmp_path)
    Path('data').mkdir(); Path('configs').mkdir(); Path('deployment').mkdir()
    Path('configs/teacher.json').write_text('{"execution_backend":"native-wine"}')
    custom = Path('deployment/teacher.json')
    custom.write_text('{"execution_backend":"standalone-managed-native","standalone_host_sha256":"pinned"}')
    Path('data/collection-session.json').write_text(json.dumps({'teacher': str(custom)}))
    captured = source_metadata('data/real.sqlite')
    assert json.loads(captured[Path('teacher.json')])['execution_backend'] == 'standalone-managed-native'
    assert json.loads(captured[Path('teacher.json')])['standalone_host_sha256'] == 'pinned'
    custom.unlink()
    with pytest.raises(FileNotFoundError):
        source_metadata('data/real.sqlite')


def test_backup_preserves_legacy_embedded_teacher_session(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    Path('data').mkdir(); Path('configs').mkdir()
    teacher = {'collector_protocol': 3, 'collector_sha256': 'native-pin', 'search_ms': 8000}
    session = json.dumps({'teacher': teacher, 'state': 'paused', 'active_db': 'data/real.sqlite'})
    Path('data/collection-session.json').write_text(session)
    Path('configs/teacher.json').write_text(json.dumps({'collector_sha256': 'native-pin'}))
    database = Path('data/real.sqlite')
    with sqlite3.connect(database) as db:
        db.execute('CREATE TABLE jobs(status TEXT)')
        db.execute("INSERT INTO jobs VALUES('complete')")
    result = backup_once(database, tmp_path / 'backups', tmp_path / 'state.json')
    saved = Path(result['directory'])
    assert (saved / 'collection-session.json').read_text() == session
    assert json.loads((saved / 'collection-session.json').read_text())['teacher'] == teacher
    assert json.loads((saved / 'teacher.json').read_text())['collector_sha256'] == 'native-pin'
    with sqlite3.connect(saved / database.name) as db:
        assert db.execute('SELECT status FROM jobs').fetchall() == [('complete',)]


def test_backup_keeps_all_runtime_configs_even_with_duplicate_basenames(tmp_path, monkeypatch):
    from tools.local_backup import source_metadata
    monkeypatch.chdir(tmp_path)
    Path('data').mkdir()
    paths = [Path('native/runtime.json'), Path('standalone/runtime.json')]
    for i, path in enumerate(paths):
        path.parent.mkdir(); path.write_text(json.dumps({'data_dir': f'worker-{i}'}))
    Path('data/collection-session.json').write_text(json.dumps({'runtimes': list(map(str, paths))}))
    captured = source_metadata('data/real.sqlite')
    manifest = json.loads(captured[Path('runtime-configs/manifest.json')])
    assert len(manifest) == 2 and manifest[0]['backup'] != manifest[1]['backup']
    for path, entry in zip(paths, manifest):
        assert entry['source'] == str(path)
        assert captured[Path(entry['backup'])] == path.read_bytes()
        assert entry['sha256'] == __import__('hashlib').sha256(path.read_bytes()).hexdigest()
    paths[0].unlink()
    with pytest.raises(FileNotFoundError): source_metadata('data/real.sqlite')
