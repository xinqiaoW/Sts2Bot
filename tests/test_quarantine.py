"""Quarantine changes queue eligibility, never the teacher, attempts or labels."""
import json
import sqlite3

import pytest

from damage_model.schema import Build, Card, Relic, digest
from damage_model.store import Store


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path / 'synthetic.sqlite')
    build = Build('OVERGROWTH', 1, (Card('DEFEND_SILENT', 1),),
                  (Relic('RING_OF_THE_SNAKE'),), (), 'synthetic-only')
    target = {'id': 'SYNTHETIC_TARGET'}
    teacher = {'test_fixture': True, 'search_ms': 8000}
    store.schedule(build, [target], ['failed-seed', 'pending-seed'], teacher)
    job = store.claim()
    store.finish(job, {'status': 'Failed', 'combatEnded': False, 'trainingObservation': None,
                       'error': 'native choice drift', 'runId': 'synthetic-run'})
    yield store, build, target, teacher, job
    store.db.close()


def snapshot(store):
    return {table: [dict(r) for r in store.db.execute(f'SELECT * FROM {table} ORDER BY rowid')]
            for table in ('builds', 'jobs', 'attempts', 'job_quarantines')}


def isolate(store, job, **overrides):
    args = dict(expected_attempts=1, reason='Repeated native choice drift', evidence='evidence/synthetic/')
    args.update(overrides)
    return store.quarantine_failed(job['id'], **args)


def test_preserves_all_evidence_and_does_not_requeue_or_export(queue, tmp_path):
    store, build, target, teacher, job = queue
    before = snapshot(store)
    record = isolate(store, job)
    after = snapshot(store)
    assert after['builds'] == before['builds'] and after['attempts'] == before['attempts']
    for old, new in zip(before['jobs'], after['jobs']):
        assert new == ({**old, 'status': 'quarantined'} if old['id'] == job['id'] else old)
    assert json.loads(record['original_job']) == before['jobs'][0]
    assert record['attempts_sha256'] == digest(before['attempts'])
    assert store.counts() == {'pending': 1, 'quarantined': 1}
    assert store.schedule(build, [target], ['failed-seed'], teacher, reactivate_excluded=True) == 0
    assert list(store.rows()) == []
    # Ordinary SQLite backups include the quarantine record and original failure.
    with sqlite3.connect(tmp_path / 'backup.sqlite') as backup:
        store.db.backup(backup)
        assert backup.execute('SELECT original_job FROM job_quarantines').fetchone()[0] == record['original_job']
        assert backup.execute('SELECT count(*) FROM attempts').fetchone()[0] == 1
    claimed = store.claim()
    assert claimed['id'] != job['id'] and claimed['seed'] == 'pending-seed'
    assert store.claim() is None


@pytest.mark.parametrize('override', [{'expected_attempts': 2}, {'reason': ''}, {'evidence': ''}])
def test_rejects_stale_or_undocumented_quarantine_without_mutation(queue, override):
    store, _, _, _, job = queue
    before = snapshot(store)
    with pytest.raises(ValueError): isolate(store, job, **override)
    assert snapshot(store) == before


@pytest.mark.parametrize('status', ['pending', 'running', 'complete', 'quarantined'])
def test_cannot_hide_active_or_successful_jobs(queue, status):
    store, _, _, _, job = queue
    with store.db: store.db.execute('UPDATE jobs SET status=? WHERE id=?', (status, job['id']))
    before = snapshot(store)
    with pytest.raises(ValueError): isolate(store, job)
    assert snapshot(store) == before


def test_cannot_repeat_quarantine_or_lose_attempts(queue):
    store, _, _, _, job = queue
    isolate(store, job)
    before = snapshot(store)
    with pytest.raises(ValueError): isolate(store, job)
    assert snapshot(store) == before


def test_missing_attempt_evidence_is_rejected(queue):
    store, _, _, _, job = queue
    with store.db: store.db.execute('DELETE FROM attempts WHERE job_id=?', (job['id'],))
    before = snapshot(store)
    with pytest.raises(ValueError, match='evidence'): isolate(store, job)
    assert snapshot(store) == before


def test_controller_continues_other_jobs_but_still_stops_for_new_failures():
    pytest.importorskip('fcntl')
    from tools.collect_continuous import next_action
    assert next_action({'complete': 5, 'pending': 2, 'quarantined': 1}, 'batch_complete') == 'collect'
    assert next_action({'complete': 5, 'quarantined': 1}, 'complete') == 'validate'
    with pytest.raises(ValueError):
        next_action({'pending': 2, 'quarantined': 1, 'failed': 1}, 'batch_complete')
