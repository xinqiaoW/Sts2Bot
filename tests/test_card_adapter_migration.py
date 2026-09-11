import json
import sqlite3
import pytest
from damage_model.store import Store
from damage_model.schema import Build, Card, canonical
from tools.change_card_adapter import migrate_card_adapter


def fixture(tmp_path):
    path=tmp_path/'old.sqlite';store=Store(path)
    build=Build('OVERGROWTH',1,(Card('BACKFLIP'),),(),(),'fixture')
    target={'id':'target','monsters':['monster']}
    teacher={'collector_protocol':2,'collector_source':'old','collector_sha256':'a','search_ms':8000,'game_sha256':'game'}
    store.schedule(build,[target],['one','two','three'],teacher)
    with store.db:
        store.db.execute("UPDATE jobs SET status='complete',result=? WHERE seed='one'",(canonical({'status':'Passed','trainingObservation':{'complete':True}}),))
        store.db.execute("UPDATE jobs SET status='quarantined' WHERE seed='three'")
        store.db.execute('CREATE TABLE source_runs(hash TEXT PRIMARY KEY,body TEXT)')
        store.db.execute('INSERT INTO source_runs VALUES(?,?)',('source','verbatim source'))
    before=[tuple(r) for r in store.db.execute('SELECT * FROM jobs ORDER BY id')]
    store.db.close()
    return path,build,target,teacher,before


def test_adapter_migration_preserves_source_and_deduplicates_old_results(tmp_path):
    path,build,target,teacher,before=fixture(tmp_path)
    new_teacher={**teacher,'collector_protocol':3,'collector_source':'new','collector_sha256':'b'}
    dest=tmp_path/'new.sqlite'
    report=migrate_card_adapter(path,dest,new_teacher)
    assert report['migrated_pending']==1 and report['completed_results_relabelled']==0
    with sqlite3.connect(path) as old:assert old.execute('SELECT * FROM jobs ORDER BY id').fetchall()==before
    new=Store(dest)
    assert new.counts()=={'pending':1}
    assert new.db.execute('SELECT body FROM source_runs').fetchone()[0]=='verbatim source'
    assert new.schedule(build,[target],['one','two','three'],new_teacher)==0
    assert new.schedule(build,[target],['new'],new_teacher)==1
    assert {r[0] for r in new.db.execute('SELECT teacher FROM jobs')}=={canonical(new_teacher)}
    assert new.db.execute('SELECT count(*) FROM attempts').fetchone()[0]==0
    new.db.close()


def test_adapter_migration_rejects_search_changes_and_active_jobs(tmp_path):
    path,build,target,teacher,before=fixture(tmp_path)
    candidate={**teacher,'collector_protocol':3,'collector_source':'new','collector_sha256':'b','search_ms':2000}
    with pytest.raises(ValueError,match='search teacher'):migrate_card_adapter(path,tmp_path/'wrong.sqlite',candidate)
    with sqlite3.connect(path) as old:old.execute("UPDATE jobs SET status='running' WHERE seed='two'")
    with pytest.raises(ValueError,match='Drain'):migrate_card_adapter(path,tmp_path/'active.sqlite',{**candidate,'search_ms':8000})
