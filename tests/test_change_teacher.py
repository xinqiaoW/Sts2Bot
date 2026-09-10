import json
import sqlite3

import pytest

from damage_model.schema import canonical, digest
from damage_model.store import Store
from tools.change_teacher import migrate_pending


def fixture_db(path):
    store = Store(path)
    old = {'search_ms':2000,'dop':1,'timeout_seconds':120}
    with store.db:
        store.db.execute("INSERT INTO builds VALUES('b','family','train','{}')")
        store.db.execute("INSERT INTO target_origins VALUES('b','run',4,4,'T')")
        store.db.execute("INSERT INTO collection_settings VALUES('target_policy','{\"name\":\"source_floor_window_v1\"}')")
        for n,status in enumerate(('complete','pending','failed','excluded_target')):
            store.db.execute('INSERT INTO jobs(id,build_id,target,seed,teacher,status,attempts,result,created) VALUES(?,?,?,?,?,?,?,?,?)',
                             (str(n),'b',canonical({'id':'T'}),str(n),canonical(old),status,2,'preserved',n))
            store.db.execute('INSERT INTO attempts(job_id,status,result,finished) VALUES(?,?,?,?)',
                             (str(n),status,'original',n))
    store.db.close()
    return old


def test_preserves_source_and_only_migrates_pending_with_new_identity(tmp_path):
    source=tmp_path/'old.sqlite'; target=tmp_path/'new.sqlite'
    old=fixture_db(source); teacher={**old,'search_ms':8000}
    before=source.read_bytes()
    report=migrate_pending(source,target,teacher)
    assert source.read_bytes()==before
    assert report['migrated_pending']==1 and report['preserved_failed_in_source']==1
    with sqlite3.connect(target) as db:
        job=db.execute('SELECT id,status,teacher,attempts,result FROM jobs').fetchone()
        assert job==(digest(['b','T','1',teacher]),'pending',canonical(teacher),0,None)
        assert db.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
        assert db.execute('SELECT source_job_id,source_attempts FROM teacher_batch_origins').fetchone()==('1',2)
        assert db.execute('SELECT count(*) FROM target_origins').fetchone()[0]==1
        assert json.loads(db.execute("SELECT value FROM collection_settings WHERE key='target_policy'").fetchone()[0])['name']=='source_floor_window_v1'
    with pytest.raises(ValueError,match='separate'):
        migrate_pending(source,target,teacher)


@pytest.mark.parametrize('change', ['running','scope','teacher'])
def test_rejects_unsafe_migration(tmp_path,change):
    source=tmp_path/'old.sqlite'; target=tmp_path/'new.sqlite'
    old=fixture_db(source); teacher={**old,'search_ms':8000}
    with sqlite3.connect(source) as db:
        if change=='running': db.execute("UPDATE jobs SET status='running' WHERE id='1'")
        if change=='scope': db.execute('DELETE FROM target_origins')
    if change=='teacher': teacher['dop']=2
    with pytest.raises(ValueError): migrate_pending(source,target,teacher)
    assert not target.exists()
