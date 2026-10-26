"""Real SQLite failure boundaries on disposable queues, never production data."""
import fcntl
import json
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from damage_model.store import Store
from damage_model.schema import Build, Card
from damage_model import result_outbox as outbox
from tools.collect_parallel import recover_receipts


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path/'jobs.sqlite')
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


@pytest.mark.parametrize('newer_complete', [False, True])
def test_late_expired_result_is_archived_without_changing_newer_work(queue,tmp_path,newer_complete):
    old=queue.claim();outbox.record_claim(tmp_path,old)
    holder=sqlite3.connect(tmp_path/'jobs.sqlite');holder.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(sqlite3.OperationalError):
            outbox.submit(queue,tmp_path,old,result_for(old))
    finally:holder.rollback();holder.close()
    receipt=outbox.path_for(tmp_path).read_bytes()
    with queue.db:queue.db.execute('UPDATE jobs SET lease_until=0')
    fresh=queue.claim()
    if newer_complete:queue.finish(fresh,result_for(fresh))
    before=[tuple(r) for r in queue.db.execute('SELECT * FROM jobs')]
    attempts=[tuple(r) for r in queue.db.execute('SELECT * FROM attempts')]
    assert outbox.recover_waiting(queue,tmp_path)=='superseded_expired'
    assert not outbox.path_for(tmp_path).exists()
    archived=list((tmp_path/'expired-results').glob('*.json'))
    assert len(archived)==1 and archived[0].read_bytes()==receipt
    assert [tuple(r) for r in queue.db.execute('SELECT * FROM jobs')]==before
    assert [tuple(r) for r in queue.db.execute('SELECT * FROM attempts')]==attempts
    assert outbox.recover_waiting(queue,tmp_path) is None
    # A new receipt can use this runtime; the archived result cannot replay.
    outbox.record_claim(tmp_path,fresh)


@pytest.mark.parametrize('tamper', ['missing_attempt', 'different_result', 'same_lease', 'duplicate_attempt'])
def test_unproven_expiry_still_stops_and_retains_the_receipt(queue,tmp_path,tamper):
    old=queue.claim();outbox.record_claim(tmp_path,old)
    holder=sqlite3.connect(tmp_path/'jobs.sqlite');holder.execute('BEGIN IMMEDIATE')
    try:
        with pytest.raises(sqlite3.OperationalError):outbox.submit(queue,tmp_path,old,result_for(old))
    finally:holder.rollback();holder.close()
    with queue.db:queue.db.execute('UPDATE jobs SET lease_until=0')
    queue.claim()
    with queue.db:
        if tamper=='missing_attempt':queue.db.execute('DELETE FROM attempts')
        elif tamper=='different_result':queue.db.execute("UPDATE attempts SET result='{}'")
        elif tamper=='same_lease':queue.db.execute('UPDATE jobs SET lease=?',(old['lease'],))
        else:queue.db.execute('INSERT INTO attempts(job_id,lease,status,result,finished) SELECT job_id,lease,status,result,finished FROM attempts')
    with pytest.raises(ValueError):outbox.recover_waiting(queue,tmp_path)
    assert outbox.path_for(tmp_path).exists()
    assert not (tmp_path/'expired-results').exists()


def test_worker_continues_after_archiving_an_expired_result(queue,tmp_path,monkeypatch):
    from damage_model import worker
    build=Build.from_dict(json.loads(queue.db.execute('SELECT body FROM builds').fetchone()[0]))
    queue.schedule(build,[{'id':'SYNTHETIC_TARGET'}],['second'],{'fixture':True})
    runtime=tmp_path/'runtime.json';runtime.write_text('{}')
    calls=[]
    class Game:
        data_dir=tmp_path
        log_path=tmp_path/'game.log'
        def stop(self):pass
        def run(self,request):
            calls.append(request['seed'])
            if len(calls)==1:
                with queue.db:queue.db.execute("UPDATE jobs SET lease_until=0 WHERE status='running'")
                newer=queue.claim()
                assert newer['seed']=='seed'
                queue.finish(newer,result_for(newer))
            return result_for({'build':build.to_dict()})
    monkeypatch.setattr(worker,'GameProcess',lambda **kwargs:Game())
    catalog=SimpleNamespace(config={'short_search_budget_ms':8000,'search_dop':1,
        'battle_timeout_seconds':120},validate=lambda b:None,
        targets=lambda b:[{'id':'SYNTHETIC_TARGET'}])
    assert worker.work(queue,catalog,runtime,3)
    assert calls==['seed','second']
    assert queue.counts()=={'complete':2}
    assert [r[0] for r in queue.db.execute('SELECT status FROM attempts ORDER BY id')]==['expired','complete','complete']
    assert len(list((tmp_path/'expired-results').glob('*.json')))==1


def test_worker_submission_waits_for_begin_without_replaying_a_result(queue,tmp_path,monkeypatch):
    job=queue.claim();result=result_for(job);outbox.record_claim(tmp_path,job)
    holder=sqlite3.connect(tmp_path/'jobs.sqlite');holder.execute('BEGIN IMMEDIATE')
    waits=[]
    def release(delay):
        waits.append(delay)
        assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
        if delay==1:holder.rollback()
    monkeypatch.setattr(outbox.time,'sleep',release)
    try:
        assert outbox.submit(queue,tmp_path,job,result,wait_for_lock=True)=='complete'
        assert waits==[.25,.5,1]
        assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0]==1
        assert queue.db.execute('SELECT attempts FROM jobs').fetchone()[0]==1
        assert not outbox.path_for(tmp_path).exists()
    finally:holder.rollback();holder.close()


def test_waiting_submission_still_refuses_a_newer_owner(queue,tmp_path,monkeypatch):
    job=queue.claim();outbox.record_claim(tmp_path,job)
    holder=sqlite3.connect(tmp_path/'jobs.sqlite');holder.execute('BEGIN IMMEDIATE')
    def replace_owner(delay):
        if delay==1:
            holder.execute("UPDATE jobs SET lease='newer-owner'")
            holder.commit()
    monkeypatch.setattr(outbox.time,'sleep',replace_owner)
    try:
        with pytest.raises(ValueError,match='Stale receipt'):
            outbox.submit(queue,tmp_path,job,result_for(job),wait_for_lock=True)
        assert outbox.path_for(tmp_path).exists()
        assert queue.db.execute('SELECT lease FROM jobs').fetchone()[0]=='newer-owner'
        assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
    finally:holder.rollback();holder.close()


def test_busy_after_a_commit_is_not_retried_by_the_waiting_path(queue,tmp_path,monkeypatch):
    job=queue.claim();outbox.record_claim(tmp_path,job)
    original=queue.finish;calls=[]
    def ambiguous_finish(job,result):
        calls.append(True)
        original(job,result)
        error=sqlite3.OperationalError('synthetic busy after commit')
        error.sqlite_errorcode=sqlite3.SQLITE_BUSY
        raise error
    with monkeypatch.context() as patch:
        patch.setattr(queue,'finish',ambiguous_finish)
        patch.setattr(outbox.time,'sleep',lambda _:pytest.fail('Ambiguous commit replay'))
        with pytest.raises(sqlite3.OperationalError):
            outbox.submit(queue,tmp_path,job,result_for(job),wait_for_lock=True)
    assert calls==[True] and outbox.path_for(tmp_path).exists()
    assert outbox.recover(queue,tmp_path)=='complete'
    assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0]==1


def test_interrupted_result_wait_retains_the_finished_battle(queue,tmp_path,monkeypatch):
    job=queue.claim();result=result_for(job);outbox.record_claim(tmp_path,job)
    holder=sqlite3.connect(tmp_path/'jobs.sqlite');holder.execute('BEGIN IMMEDIATE')
    def interrupt(delay):
        if delay==1:raise KeyboardInterrupt()
    try:
        with monkeypatch.context() as patch:
            patch.setattr(outbox.time,'sleep',interrupt)
            with pytest.raises(KeyboardInterrupt):
                outbox.submit(queue,tmp_path,job,result,wait_for_lock=True)
        assert json.loads(outbox.path_for(tmp_path).read_text())['result']==result
        assert queue.counts()=={'running':1}
    finally:holder.rollback();holder.close()
    assert outbox.recover(queue,tmp_path)=='complete'
    assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0]==1


@pytest.mark.parametrize('action', ['finish', 'retry_startup', 'retry_or_quarantine_native', 'claimed'])
@pytest.mark.parametrize('newer_complete', [False, True])
def test_expiry_between_receipt_read_and_successful_begin_preserves_new_owner(queue, tmp_path, monkeypatch, action, newer_complete):
    old = queue.claim()
    outbox.record_claim(tmp_path, old)
    peer = Store(tmp_path/'jobs.sqlite')
    holder = sqlite3.connect(tmp_path/'jobs.sqlite')
    holder.execute('BEGIN IMMEDIATE')
    snapshot = {}
    waits = []

    def expire_before_next_begin(delay):
        waits.append(delay)
        assert waits == [.25]  # The next BEGIN succeeds before the bounded retry exhausts.
        assert not queue.db.in_transaction
        snapshot['receipt'] = outbox.path_for(tmp_path).read_bytes()
        holder.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (old['id'],))
        holder.commit()
        fresh = peer.claim()
        assert fresh['lease'] != old['lease']
        if newer_complete:
            peer.finish(fresh, result_for(fresh))
        snapshot['jobs'] = list(map(tuple, peer.db.execute('SELECT * FROM jobs')))
        snapshot['attempts'] = list(map(tuple, peer.db.execute('SELECT * FROM attempts')))

    monkeypatch.setattr(outbox.time, 'sleep', expire_before_next_begin)
    evidence = tmp_path/'failure.txt'
    evidence.write_text('synthetic failure evidence')
    options = dict(max_attempts=3, reason='synthetic', evidence=str(evidence)) if action == 'retry_or_quarantine_native' else {}
    result = (result_for(old) if action == 'finish' else
              dict(status='NativeStartupCacheFailure', error='synthetic'))
    try:
        status = (outbox.recover_waiting(queue, tmp_path) if action == 'claimed' else
                  outbox.submit(queue, tmp_path, old, result, action, wait_for_lock=True, **options))
        assert status == ('recovered_pending' if action == 'claimed' else 'superseded_expired')
        assert list(map(tuple, queue.db.execute('SELECT * FROM jobs'))) == snapshot['jobs']
        assert list(map(tuple, queue.db.execute('SELECT * FROM attempts'))) == snapshot['attempts']
        assert not queue.db.in_transaction and not outbox.path_for(tmp_path).exists()
        archived = list((tmp_path/'expired-results').glob('*.json'))
        if action == 'claimed':
            assert archived == []
        else:
            assert len(archived) == 1 and archived[0].read_bytes() == snapshot['receipt']
    finally:
        holder.close()
        peer.db.close()


@pytest.mark.parametrize('proof', ['missing', 'different', 'duplicate'])
def test_lease_race_without_unique_expiry_proof_stops_and_retains_receipt(queue, tmp_path, monkeypatch, proof):
    old = queue.claim()
    outbox.record_claim(tmp_path, old)
    peer = Store(tmp_path/'jobs.sqlite')
    holder = sqlite3.connect(tmp_path/'jobs.sqlite')
    holder.execute('BEGIN IMMEDIATE')
    snapshot = {}

    def replace_before_next_begin(delay):
        assert delay == .25
        holder.execute('UPDATE jobs SET lease_until=0 WHERE id=?', (old['id'],))
        holder.commit()
        peer.claim()
        with peer.db:
            if proof == 'missing':
                peer.db.execute('DELETE FROM attempts')
            elif proof == 'different':
                peer.db.execute("UPDATE attempts SET result='{}'")
            else:
                peer.db.execute('INSERT INTO attempts(job_id,lease,status,result,finished) SELECT job_id,lease,status,result,finished FROM attempts')
        snapshot['jobs'] = list(map(tuple, peer.db.execute('SELECT * FROM jobs')))
        snapshot['attempts'] = list(map(tuple, peer.db.execute('SELECT * FROM attempts')))
        snapshot['receipt'] = outbox.path_for(tmp_path).read_bytes()

    monkeypatch.setattr(outbox.time, 'sleep', replace_before_next_begin)
    try:
        with pytest.raises(ValueError):
            outbox.submit(queue, tmp_path, old, result_for(old), wait_for_lock=True)
        assert outbox.path_for(tmp_path).read_bytes() == snapshot['receipt']
        assert list(map(tuple, queue.db.execute('SELECT * FROM jobs'))) == snapshot['jobs']
        assert list(map(tuple, queue.db.execute('SELECT * FROM attempts'))) == snapshot['attempts']
        assert not (tmp_path/'expired-results').exists() and not queue.db.in_transaction
    finally:
        holder.close()
        peer.db.close()
