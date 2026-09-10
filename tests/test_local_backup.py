import json
import sqlite3
from contextlib import nullcontext
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
    for phase in ('recent-history', 'full-archive'):
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
    for phase in ('recent-history', 'full-archive'):
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
