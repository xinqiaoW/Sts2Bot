"""SQLite contention tests use disposable synthetic databases only."""
import json
import sqlite3

import pytest

from damage_model.schema import Build, Card, canonical
from damage_model.store import Store


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path/'synthetic.sqlite')
    build = Build('OVERGROWTH', 1, (Card('DEFEND_SILENT', 1),), (), (), 'synthetic-only')
    store.schedule(build, [{'id': 'SYNTHETIC_TARGET'}], ['seed'], {'fixture': True})
    store.db.execute('PRAGMA busy_timeout=0')
    yield store
    store.db.close()


def observation(job):
    return {'status': 'Passed', 'combatEnded': True, 'runId': 'synthetic-only',
        'collectionRequest': {'seed': job['seed'], 'unchanged': True},
        'trainingObservation': {'complete': True, 'initialHp': 70, 'initialMaxHp': 70,
            'finalHp': 66, 'finalMaxHp': 70, 'netHpLoss': 4, 'playerDied': False,
            'initialBuild': {'character': 'SILENT', 'ascension': 10,
                'actId': job['build']['act_id'], 'relics': [],
                'cards': [{'id': c['id'], 'upgradeLevel': c['upgrade']}
                          for c in job['build']['cards']]}}}


def hold(queue):
    holder = sqlite3.connect(queue.db.execute('PRAGMA database_list').fetchone()[2])
    holder.execute('BEGIN IMMEDIATE')
    return holder


@pytest.mark.parametrize('passed', [True, False])
def test_finish_released_lock_keeps_exact_result_and_one_attempt(queue, monkeypatch, passed):
    job = queue.claim()
    result = observation(job) if passed else {'status': 'Failed', 'error': 'synthetic failure'}
    encoded = canonical(result)
    holder = hold(queue)

    def release(_):
        assert not queue.db.in_transaction
        assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
        holder.rollback()

    monkeypatch.setattr('damage_model.store.time.sleep', release)
    try:
        expected = 'complete' if passed else 'failed'
        assert queue.finish(job, result) == expected
    finally:
        holder.close()
    row = queue.db.execute('SELECT status,result,attempts,lease FROM jobs').fetchone()
    assert tuple(row) == (expected, encoded, 1, job['lease'])
    assert [tuple(r) for r in queue.db.execute('SELECT status,result,lease FROM attempts')] == [
        (expected, encoded, job['lease'])]
    assert canonical(result) == encoded
    with pytest.raises(ValueError, match='Stale'):
        queue.finish(job, result)
    assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 1
    assert not queue.db.in_transaction


def test_persistent_finish_lock_preserves_lease_result_and_attempts(queue, monkeypatch):
    job = queue.claim()
    before = list(queue.db.iterdump())
    holder = hold(queue)
    delays, trace = [], []
    monkeypatch.setattr('damage_model.store.time.sleep', delays.append)
    queue.db.set_trace_callback(trace.append)
    try:
        with pytest.raises(sqlite3.OperationalError) as error:
            queue.finish(job, observation(job))
        assert error.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
        assert trace.count('BEGIN IMMEDIATE') == 3 and delays == [0.25, 0.5]
        assert list(queue.db.iterdump()) == before
        assert not queue.db.in_transaction
    finally:
        holder.rollback()
        holder.close()


def test_finish_rechecks_lease_after_waiting(queue, monkeypatch):
    old = queue.claim()
    peer = Store(queue.db.execute('PRAGMA database_list').fetchone()[2])
    holder = hold(queue)
    holder.execute('UPDATE jobs SET lease_until=0')
    replacement = []

    def reclaim(_):
        holder.commit()
        replacement.append(peer.claim())

    monkeypatch.setattr('damage_model.store.time.sleep', reclaim)
    try:
        with pytest.raises(ValueError, match='Stale'):
            queue.finish(old, observation(old))
        assert queue.db.execute('SELECT lease FROM jobs').fetchone()[0] == replacement[0]['lease']
        assert [r[0] for r in queue.db.execute('SELECT status FROM attempts')] == ['expired']
        assert queue.finish(replacement[0], observation(replacement[0])) == 'complete'
    finally:
        holder.close()
        peer.db.close()


def test_invalid_observation_is_rejected_before_waiting_for_a_write(queue, monkeypatch):
    job = queue.claim()
    result = observation(job)
    result['trainingObservation']['initialBuild']['cards'][0]['upgradeLevel'] = 0
    holder = hold(queue)
    monkeypatch.setattr('damage_model.store.time.sleep', lambda _: pytest.fail('Invalid result waited for DB'))
    try:
        with pytest.raises(ValueError, match='starting deck'):
            queue.finish(job, result)
    finally:
        holder.rollback()
        holder.close()


def test_error_after_update_rolls_back_without_replaying_transaction(queue, monkeypatch):
    job = queue.claim()
    queue.db.execute("CREATE TRIGGER fail_attempt BEFORE INSERT ON attempts BEGIN SELECT RAISE(ABORT,'synthetic failure'); END")
    before = list(queue.db.iterdump())
    monkeypatch.setattr('damage_model.store.time.sleep', lambda _: pytest.fail('Transaction body was retried'))
    with pytest.raises(sqlite3.IntegrityError, match='synthetic failure'):
        queue.finish(job, observation(job))
    assert list(queue.db.iterdump()) == before
    assert not queue.db.in_transaction


@pytest.mark.parametrize('operation', ['retry_startup', 'retry_or_quarantine_native', 'quarantine_failed'])
def test_native_retry_and_isolation_released_lock_record_once(queue, tmp_path, monkeypatch, operation):
    job = queue.claim()
    result = {'status': 'NativeEnumCacheFailure', 'error': 'synthetic only'}
    evidence = tmp_path/'synthetic-evidence.json'
    evidence.write_text(json.dumps(result))
    if operation == 'quarantine_failed':
        assert queue.finish(job, result) == 'failed'
    holder = hold(queue)
    monkeypatch.setattr('damage_model.store.time.sleep', lambda _: holder.rollback())
    try:
        if operation == 'quarantine_failed':
            queue.quarantine_failed(job['id'], expected_attempts=1, reason='synthetic', evidence=str(evidence))
            expected = 'quarantined'
        elif operation == 'retry_startup':
            expected = queue.retry_startup(job, result)
            assert expected == 'retry'
        else:
            expected = queue.retry_or_quarantine_native(job, result, max_attempts=3,
                reason='synthetic', evidence=str(evidence))
            assert expected == 'retry'
    finally:
        holder.close()
    assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 1
    assert queue.db.execute('SELECT status FROM jobs').fetchone()[0] == ('pending' if expected == 'retry' else expected)
    assert not queue.db.in_transaction


def test_schedule_released_lock_deduplicates_jobs(queue, monkeypatch):
    build = Build('OVERGROWTH', 1, (Card('DEFEND_SILENT', 1),), (), (), 'synthetic-only')
    holder = hold(queue)
    monkeypatch.setattr('damage_model.store.time.sleep', lambda _: holder.rollback())
    try:
        assert queue.schedule(build, [{'id': 'SYNTHETIC_TARGET'}], ['seed', 'second'], {'fixture': True}) == 1
        assert queue.schedule(build, [{'id': 'SYNTHETIC_TARGET'}], ['seed', 'second'], {'fixture': True}) == 0
        assert queue.counts() == {'pending': 2}
    finally:
        holder.close()
