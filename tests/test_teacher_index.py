import json

import pytest

from damage_model.priority_store import PriorityStore
from damage_model.schema import Build, Card, Relic, canonical
from damage_model.store import Store


def test_reopening_legacy_store_indexes_full_teacher_validation(tmp_path):
    path = tmp_path / 'legacy.sqlite'
    store = Store(path)
    store.db.execute('DROP INDEX jobs_teacher')
    store.db.executemany('INSERT INTO jobs(id,teacher) VALUES(?,?)', [
        ('first', '{"search_ms":8000}'), ('last', '{"search_ms":2000}'),
    ])
    store.db.commit()
    store.db.close()

    reopened = Store(path)
    try:
        plan = ' '.join(row[3] for row in reopened.db.execute(
            'EXPLAIN QUERY PLAN SELECT DISTINCT teacher FROM jobs'))
        assert 'COVERING INDEX jobs_teacher' in plan
        assert {row[0] for row in reopened.db.execute('SELECT DISTINCT teacher FROM jobs')} == {
            '{"search_ms":8000}', '{"search_ms":2000}',
        }
    finally:
        reopened.db.close()


def test_indexed_queue_validation_still_rejects_one_different_teacher(tmp_path):
    primary, fallback = Store(tmp_path / 'real.sqlite'), Store(tmp_path / 'mutations.sqlite')
    try:
        for store in (primary, fallback):
            store.db.executemany('INSERT INTO jobs(id,teacher) VALUES(?,?)', [
                (str(i), json.dumps({'search_ms': 8000}, separators=(',', ':')))
                for i in range(20)
            ])
            store.db.commit()
        PriorityStore(primary, fallback, {'search_ms': 8000})
        fallback.db.execute('INSERT INTO jobs(id,teacher) VALUES(?,?)',
                            ('unexpected', '{"search_ms":2000}'))
        fallback.db.commit()
        with pytest.raises(ValueError, match='same frozen teacher'):
            PriorityStore(primary, fallback, {'search_ms': 8000})
    finally:
        primary.db.close()
        fallback.db.close()


def example_build():
    return Build('OVERGROWTH', 1, (Card('DEFEND_SILENT'),),
                 (Relic('RING_OF_THE_SNAKE'),), (), 'test')


def test_scheduling_does_not_scan_every_matching_teacher(tmp_path):
    store = Store(tmp_path / 'queue.sqlite')
    try:
        teacher = {'search_ms': 8000}
        build = example_build()
        store.schedule(build, [{'id': 'TEST'}], range(2500), teacher)
        steps = 0

        def bounded_work():
            nonlocal steps
            steps += 1
            return steps > 500

        # Bound actual SQLite work on an unanalyzed queue, independently of
        # cache warmth or machine speed. Revalidating this build adds no jobs.
        store.db.set_progress_handler(bounded_work, 1)
        assert store.schedule(build, [], [], teacher) == 0
    finally:
        store.db.set_progress_handler(None, 0)
        store.db.close()


@pytest.mark.parametrize('unexpected', [None, {'search_ms': 7000}, {'search_ms': 9000}])
def test_scheduling_rejects_any_other_or_missing_teacher(tmp_path, unexpected):
    store = Store(tmp_path / 'queue.sqlite')
    try:
        teacher = {'search_ms': 8000}
        build = example_build()
        store.schedule(build, [{'id': 'TEST'}], ['seed'], teacher)
        store.db.execute('INSERT INTO jobs(id,teacher) VALUES(?,?)',
                         ('unexpected', None if unexpected is None else canonical(unexpected)))
        store.db.commit()
        with pytest.raises(ValueError, match='different teacher'):
            store.schedule(build, [], [], teacher)
    finally:
        store.db.close()
