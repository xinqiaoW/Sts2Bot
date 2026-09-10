"""Real SQLite contention on synthetic queues must not consume combat attempts."""
import sqlite3
from unittest.mock import Mock

import pytest

from damage_model.priority_store import PriorityStore
from damage_model.schema import Build, Card
from damage_model.store import Store


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path/'synthetic.sqlite')
    build = Build('OVERGROWTH', 1, (Card('DEFEND_SILENT'),), (), (), 'synthetic-only')
    store.schedule(build, [{'id': 'SYNTHETIC_TARGET'}], ['first', 'second'], {'fixture': True})
    store.db.execute('PRAGMA busy_timeout=0')
    yield store
    store.db.close()


def holder_for(queue):
    holder = sqlite3.connect(queue.db.execute('PRAGMA database_list').fetchone()[2])
    holder.execute('BEGIN IMMEDIATE')
    return holder


def test_released_lock_expires_and_claims_exactly_once(queue, monkeypatch, capsys):
    previous = queue.claim()
    with queue.db:
        queue.db.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (previous['id'],))
    holder = holder_for(queue)

    def release(delay):
        assert not queue.db.in_transaction
        assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
        assert queue.db.execute('SELECT attempts FROM jobs WHERE id=?', (previous['id'],)).fetchone()[0] == 1
        holder.rollback()

    monkeypatch.setattr('damage_model.store.time.sleep', release)
    try:
        claimed = queue.claim()
    finally:
        holder.close()
    assert claimed['id'] == previous['id'] and claimed['lease'] != previous['lease']
    assert queue.db.execute('SELECT attempts FROM jobs WHERE id=?', (claimed['id'],)).fetchone()[0] == 2
    assert [tuple(r) for r in queue.db.execute('SELECT job_id,lease,status FROM attempts')] == [
        (previous['id'], previous['lease'], 'expired')]
    assert queue.claim()['id'] != claimed['id']
    assert queue.claim() is None
    assert not queue.db.in_transaction
    assert '"event": "claim_busy"' in capsys.readouterr().out


def test_persistent_lock_stops_after_three_begins_without_changes(queue, monkeypatch):
    before = list(queue.db.iterdump())
    holder = holder_for(queue)
    trace, delays = [], []
    queue.db.set_trace_callback(trace.append)
    monkeypatch.setattr('damage_model.store.time.sleep', delays.append)
    try:
        with pytest.raises(sqlite3.OperationalError) as error:
            queue.claim()
        assert error.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
        assert trace.count('BEGIN IMMEDIATE') == 3 and delays == [0.25, 0.5]
        assert not queue.db.in_transaction
        assert list(queue.db.iterdump()) == before
    finally:
        holder.rollback()
        holder.close()


def test_existing_transaction_is_not_retried_or_rolled_back(queue, monkeypatch):
    queue.db.execute('BEGIN')
    monkeypatch.setattr('damage_model.store.time.sleep', lambda _: pytest.fail('Unexpected retry'))
    with pytest.raises(sqlite3.OperationalError):
        queue.claim()
    assert queue.db.in_transaction
    queue.db.rollback()


@pytest.mark.parametrize('code', [sqlite3.SQLITE_LOCKED, sqlite3.SQLITE_IOERR, sqlite3.SQLITE_CORRUPT])
def test_other_operational_errors_propagate_unchanged(queue, monkeypatch, code):
    error = sqlite3.OperationalError('synthetic database error')
    error.sqlite_errorcode = code
    db = Mock(in_transaction=False)
    db.execute.side_effect = error
    monkeypatch.setattr('damage_model.store.time.sleep', lambda _: pytest.fail('Unexpected retry'))
    with monkeypatch.context() as patch:
        patch.setattr(queue, 'db', db)
        with pytest.raises(sqlite3.OperationalError) as raised:
            queue.claim()
        assert raised.value is error and db.execute.call_count == 1


def test_busy_real_queue_does_not_fall_through_to_mutations(queue, tmp_path, monkeypatch):
    fallback = Store(tmp_path/'fallback.sqlite')
    priority = PriorityStore(queue, fallback, {'fixture': True})
    holder = holder_for(queue)
    monkeypatch.setattr(fallback, 'claim', lambda _: pytest.fail('Real priority was lost'))
    monkeypatch.setattr('damage_model.store.time.sleep', lambda _: holder.rollback())
    try:
        assert priority.claim()['collection_dataset'] == 'real'
        assert queue.db.execute('SELECT sum(attempts) FROM jobs').fetchone()[0] == 1
    finally:
        holder.close()
        fallback.db.close()


def test_interruption_during_backoff_does_not_claim_a_job(queue, monkeypatch):
    holder = holder_for(queue)

    def interrupt(_):
        raise KeyboardInterrupt

    monkeypatch.setattr('damage_model.store.time.sleep', interrupt)
    try:
        with pytest.raises(KeyboardInterrupt):
            queue.claim()
        assert queue.db.execute('SELECT sum(attempts) FROM jobs').fetchone()[0] == 0
        assert not queue.db.in_transaction
    finally:
        holder.rollback()
        holder.close()
