"""Real SQLite failure boundaries on disposable queues, never production data."""
import fcntl
import json
import sqlite3
from pathlib import Path

import pytest

from damage_model.store import Store
from damage_model.schema import Build, Card
from damage_model import result_outbox as outbox
from tools.collect_parallel import recover_receipts


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path/'jobs.sqlite', write_wait_seconds=.02)
    build = Build('OVERGROWTH', 1, (Card('DEFEND_SILENT', 1),), (), (), 'synthetic-only')
    store.schedule(build, [{'id':'SYNTHETIC_TARGET'}], ['seed'], {'fixture':True})
    store.db.execute('PRAGMA busy_timeout=0')
    yield store
    store.db.close()


def result_for(job):
    return dict(status='Passed', combatEnded=True, runId='synthetic', trainingObservation=dict(
        complete=True, initialHp=70, initialMaxHp=70, finalHp=65, finalMaxHp=70,
        netHpLoss=5, playerDied=False, initialBuild=dict(character='SILENT', ascension=10,
        actId=job['build']['act_id'], cards=[dict(id='DEFEND_SILENT',upgradeLevel=1)], relics=[])))


def test_locked_completed_result_survives_restart_without_replaying_combat(queue, tmp_path):
    job=queue.claim(); result=result_for(job); outbox.record_claim(tmp_path, job)
    holder=sqlite3.connect(tmp_path/'jobs.sqlite'); holder.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(sqlite3.OperationalError):outbox.submit(queue,tmp_path,job,result)
        receipt=json.loads(outbox.path_for(tmp_path).read_text())
        assert receipt['result']==result and queue.counts()=={'running':1}
    finally:
        holder.rollback();holder.close()
    reopened=Store(tmp_path/'jobs.sqlite')
    try:
        assert outbox.recover(reopened,tmp_path)=='complete'
        assert outbox.recover(reopened,tmp_path) is None
        assert reopened.counts()=={'complete':1}
        assert reopened.db.execute('SELECT count(*) FROM attempts').fetchone()[0]==1
        assert json.loads(reopened.db.execute('SELECT result FROM attempts').fetchone()[0])==result
    finally:reopened.db.close()


def test_crash_after_commit_is_idempotent(queue,tmp_path,monkeypatch):
    job=queue.claim();outbox.record_claim(tmp_path,job)
    unlink=Path.unlink
    def crashed(path,*a,**kw):
        if path==outbox.path_for(tmp_path):raise OSError('simulated crash after commit')
        return unlink(path,*a,**kw)
    with monkeypatch.context() as m:
        m.setattr(Path,'unlink',crashed)
        with pytest.raises(OSError):outbox.submit(queue,tmp_path,job,result_for(job))
    assert outbox.recover(queue,tmp_path)=='complete'
    assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0]==1


def test_claim_only_interruption_is_recorded_and_requeued_once(queue,tmp_path):
    job=queue.claim();outbox.record_claim(tmp_path,job)
    assert recover_receipts(queue,[{'data_dir':str(tmp_path)}])[0]['status']=='recovered_pending'
    assert queue.counts()=={'pending':1}
    row=queue.db.execute('SELECT status,result FROM attempts').fetchone()
    assert row['status']=='interrupted' and json.loads(row['result'])['claim']==job
    replacement=queue.claim()
    assert replacement['lease']!=job['lease']
    assert queue.finish(replacement,result_for(replacement))=='complete'
    assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0]==2


def test_live_owner_prevents_pool_recovery(queue,tmp_path):
    job=queue.claim();outbox.record_claim(tmp_path,job)
    with (tmp_path/'collector.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):recover_receipts(queue,[{'data_dir':str(tmp_path)}])
    assert queue.counts()=={'running':1} and outbox.path_for(tmp_path).exists()


def test_stale_result_never_overwrites_new_owner(queue,tmp_path):
    old=queue.claim();outbox.record_claim(tmp_path,old)
    holder=sqlite3.connect(tmp_path/'jobs.sqlite');holder.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(sqlite3.OperationalError):outbox.submit(queue,tmp_path,old,result_for(old))
    finally:holder.rollback();holder.close()
    with queue.db:queue.db.execute('UPDATE jobs SET lease_until=0')
    fresh=queue.claim()
    with pytest.raises(ValueError,match='differs'):outbox.recover(queue,tmp_path)
    assert outbox.path_for(tmp_path).exists()
    assert queue.db.execute('SELECT lease FROM jobs').fetchone()[0]==fresh['lease']


def test_invalid_observation_keeps_original_evidence_and_is_not_a_label(queue,tmp_path):
    job=queue.claim();outbox.record_claim(tmp_path,job)
    result=result_for(job);result['trainingObservation']['initialBuild']['cards']=[]
    assert outbox.submit(queue,tmp_path,job,result)=='failed'
    stored=json.loads(queue.db.execute('SELECT result FROM attempts').fetchone()[0])
    assert stored['status']=='InvalidObservation' and stored['native_result']==result
