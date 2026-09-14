"""Keep per-build provenance checks bounded without changing queue data."""
import sqlite3

import pytest

from damage_model.schema import Build, Card
from damage_model.store import Store


def table_rows(db):
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {name: [tuple(r) for r in db.execute(f'SELECT * FROM "{name}" ORDER BY rowid')]
            for name in tables}


def test_existing_database_index_preserves_all_rows_and_claim_order(tmp_path):
    path = tmp_path/'existing.sqlite'
    old = Store(path)
    old.db.execute('DROP INDEX IF EXISTS jobs_build')
    build = Build('OVERGROWTH', 1, (Card('DEFEND_SILENT'),), (), (), 'synthetic-only')
    old.schedule(build, [{'id': 'A'}, {'id': 'B'}], ['one', 'two'], {'fixture': True})
    first = old.claim()
    old.finish(first, {'status': 'Failed', 'error': 'synthetic-only'})
    before = table_rows(old.db)
    expected_next = old.db.execute("SELECT id FROM jobs WHERE status='pending' ORDER BY created LIMIT 1").fetchone()[0]
    old.db.close()
    upgraded = Store(path)
    try:
        assert table_rows(upgraded.db) == before
        assert upgraded.db.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
        assert [r[2] for r in upgraded.db.execute('PRAGMA index_info(jobs_build)')] == ['build_id']
        second_open = Store(path)
        second_open.db.close()
        assert table_rows(upgraded.db) == before
        assert upgraded.claim()['id'] == expected_next
    finally:
        upgraded.db.close()


@pytest.mark.parametrize('invalid_target', [False, True])
def test_target_audit_same_rows_without_scanning_unrelated_jobs(tmp_path, invalid_target):
    store = Store(tmp_path/'large-synthetic.sqlite')
    try:
        # Deliberately synthetic rows; never used as training observations.
        store.db.executemany('INSERT INTO jobs(id,build_id,target,result) VALUES(?,?,?,?)',
            [(str(i), 'unrelated-'+str(i), '{"id":"OTHER"}', 'x'*4096) for i in range(2000)])
        targets = ['A', 'OUTSIDE' if invalid_target else 'B']
        store.db.executemany('INSERT INTO jobs(id,build_id,target,status) VALUES(?,?,?,?)',
            [('target-'+str(i), 'chosen', '{"id":"'+target+'"}', status)
             for i, (target, status) in enumerate(zip(targets, ['pending', 'complete']))])
        store.db.commit()
        sql = 'SELECT target FROM jobs WHERE build_id=?'
        before = table_rows(store.db)
        reference = [tuple(r) for r in store.db.execute(sql.replace('jobs WHERE', 'jobs NOT INDEXED WHERE'), ('chosen',))]
        steps = []
        store.db.set_progress_handler(lambda: steps.append(1) or (len(steps) > 100), 1)
        actual = [tuple(r) for r in store.db.execute(sql, ('chosen',))]
        store.db.set_progress_handler(None, 0)
        assert actual == reference
        import json
        assert any(json.loads(r[0])['id'] not in {'A', 'B'} for r in actual) == invalid_target
        assert table_rows(store.db) == before
    finally:
        store.db.close()
