"""Lease expiration must log and release exactly the same jobs."""
import pytest

from damage_model.schema import Build, Card
from damage_model.store import Store


@pytest.mark.parametrize('after_insert', [98.0, 102.0])
def test_clock_crossing_between_expiration_statements_preserves_audit(tmp_path, monkeypatch, after_insert):
    store = Store(tmp_path/'synthetic.sqlite')
    try:
        build = Build('OVERGROWTH', 1, (Card('DEFEND_SILENT'),), (), (), 'synthetic-only')
        store.schedule(build, [{'id': 'SYNTHETIC'}], ['old', 'future'], {'fixture': True})
        old, future = store.claim(), store.claim()
        with store.db:
            store.db.execute('UPDATE jobs SET lease_until=99 WHERE id=?', (old['id'],))
            store.db.execute('UPDATE jobs SET lease_until=101 WHERE id=?', (future['id'],))
        clock = [100.0]
        monkeypatch.setattr('damage_model.store.time.time', lambda: clock[0])

        def advance(sql):
            if sql.lstrip().startswith('INSERT INTO attempts'):
                clock[0] = after_insert

        store.db.set_trace_callback(advance)
        reclaimed = store.claim()
        store.db.set_trace_callback(None)
        assert reclaimed is not None and reclaimed['id'] == old['id']
        assert reclaimed['lease'] != old['lease']
        assert [tuple(r) for r in store.db.execute('SELECT job_id,lease,status FROM attempts')] == [
            (old['id'], old['lease'], 'expired')]
        unchanged = store.db.execute('SELECT status,lease,attempts FROM jobs WHERE id=?', (future['id'],)).fetchone()
        assert tuple(unchanged) == ('running', future['lease'], 1)
        clock[0] = 102.0
        next_job = store.claim()
        assert next_job['id'] == future['id']
        assert [tuple(r) for r in store.db.execute('SELECT job_id,lease,status FROM attempts ORDER BY id')] == [
            (old['id'], old['lease'], 'expired'), (future['id'], future['lease'], 'expired')]
    finally:
        store.db.close()
