"""Controller refills retain their candidate/sequence during pre-BEGIN contention."""
from argparse import Namespace
from pathlib import Path
import sqlite3
import pytest
from tools.collect_continuous import Controller


@pytest.fixture
def controller(tmp_path):
    value = object.__new__(Controller)
    value.args = Namespace(stop_at=None)
    value.stop_requested = False
    value.stop_path = tmp_path/'stop'
    return value


def test_all_controller_stores_wait_without_replaying_sequence_updates(controller,tmp_path,monkeypatch):
    for name in ('real','mutations','targeted'):
        store=controller.open_store(tmp_path/(name+'.sqlite'))
        store.db.execute('PRAGMA busy_timeout=0')
        with store.db:store.db.execute("INSERT INTO collection_settings VALUES('mutation_sequence','0')")
        holder=sqlite3.connect(tmp_path/(name+'.sqlite'));holder.execute('BEGIN IMMEDIATE')
        trace=[];store.db.set_trace_callback(trace.append)
        def release(delay):
            assert not store.db.in_transaction
            assert store.db.execute("SELECT value FROM collection_settings WHERE key='mutation_sequence'").fetchone()[0]=='0'
            if delay==1:holder.rollback()
        monkeypatch.setattr('damage_model.store.time.sleep',release)
        try:
            store._begin_write('mutation_refill')
            with store.db:store.db.execute("UPDATE collection_settings SET value='1' WHERE key='mutation_sequence'")
            assert trace.count('BEGIN IMMEDIATE')==4
            assert sum(s.startswith('UPDATE collection_settings') for s in trace)==1
            assert store.db.execute("SELECT value FROM collection_settings WHERE key='mutation_sequence'").fetchone()[0]=='1'
            assert store.counts()=={}
        finally:holder.close();store.db.close()


@pytest.mark.parametrize('stop_kind',['marker','request','deadline'])
def test_wait_honors_stop_without_writing(controller,tmp_path,monkeypatch,stop_kind):
    store=controller.open_store(tmp_path/'jobs.sqlite');store.db.execute('PRAGMA busy_timeout=0')
    holder=sqlite3.connect(tmp_path/'jobs.sqlite');holder.execute('BEGIN IMMEDIATE')
    before=list(store.db.iterdump())
    def stop(delay):
        if stop_kind=='marker':controller.stop_path.touch()
        elif stop_kind=='request':controller.stop_requested=True
        else:controller.args.stop_at=1
    monkeypatch.setattr('damage_model.store.time.sleep',stop)
    try:
        with pytest.raises(KeyboardInterrupt):store._begin_write('mutation_refill')
        assert not store.db.in_transaction
        assert list(store.db.iterdump())==before
    finally:holder.rollback();holder.close();store.db.close()


def test_stop_after_begin_releases_only_the_empty_transaction(controller,tmp_path,monkeypatch):
    store=controller.open_store(tmp_path/'jobs.sqlite')
    original=store._begin_write_bounded
    def stop_after_lock(operation):
        original(operation)
        controller.stop_path.touch()
    monkeypatch.setattr(store,'_begin_write_bounded',stop_after_lock)
    try:
        with pytest.raises(KeyboardInterrupt):store._begin_write('mutation_refill')
        assert not store.db.in_transaction and store.counts()=={}
    finally:store.db.close()


def test_statement_busy_is_not_retried(controller,tmp_path,monkeypatch):
    store=controller.open_store(tmp_path/'jobs.sqlite');original=store.db;calls=[]
    error=sqlite3.OperationalError('synthetic busy during a statement');error.sqlite_errorcode=sqlite3.SQLITE_BUSY
    class Connection:
        in_transaction=False
        def execute(self,sql,*args):
            calls.append(sql)
            if sql.startswith('INSERT'):raise error
            return original.execute(sql,*args)
        def __enter__(self):return self
        def __exit__(self,*exc):return original.__exit__(*exc)
    monkeypatch.setattr(store,'db',Connection())
    monkeypatch.setattr('damage_model.store.time.sleep',lambda _:pytest.fail('Statement replay'))
    from damage_model.schema import Build,Card
    build=Build('OVERGROWTH',1,(Card('DEFEND_SILENT'),),(),(),'synthetic-only')
    try:
        with pytest.raises(sqlite3.OperationalError) as caught:store.add_build(build)
        assert caught.value is error and calls.count('BEGIN IMMEDIATE')==1
        assert sum(sql.startswith('INSERT') for sql in calls)==1
        assert original.execute('SELECT count(*) FROM builds').fetchone()[0]==0
    finally:original.close()
