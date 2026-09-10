"""Source floor windows and reversible queue migration; no game processes."""
from copy import deepcopy
import pytest

from damage_model.catalog import Catalog
from damage_model.run_import import import_run, reconstruct
from damage_model.store import Store
from damage_model.target_scope import (recorded_floors, window_for_origin,
    plan_window, migrate_window, require_policy)
from tools.migrate_target_scope import preserved_hashes
from test_run_import import catalog, run, node


def test_numeric_floor_window_skips_noncombat_and_never_crosses_act(catalog):
    ids = [t['id'] for t in catalog.acts['OVERGROWTH']['encounters'][:4]]
    run = {'acts':['ACT.OVERGROWTH', 'ACT.OVERGROWTH'], 'map_point_history':[
        [node('ENCOUNTER.'+ids[0]), node('EVENT.CAMP'), node('ENCOUNTER.'+ids[1]),
         node('EVENT.SHOP'), node('ENCOUNTER.'+ids[2]), node('ENCOUNTER.'+ids[3])],
        [node('ENCOUNTER.'+ids[0])]]}
    floors = recorded_floors(run)
    origin = {'floor':3, 'act':1, 'act_id':'OVERGROWTH', 'target':ids[1]}
    targets, audit = window_for_origin(floors, origin, catalog)
    assert {t['id'] for t in targets} == set(ids[:3])
    assert [r['floor'] for r in audit['selected']] == [1,3,5]
    targets, audit = window_for_origin(floors, {**origin,'floor':6,'target':ids[3]}, catalog)
    assert {t['id'] for t in targets} == set(ids[2:])
    assert [r['floor'] for r in audit['selected']] == [5,6]


def test_neighbors_do_not_require_reconstructable_neighbor_builds(catalog, run):
    ids = [t['id'] for t in catalog.acts['OVERGROWTH']['encounters'][:3]]
    run['map_point_history'][0][2]['rooms'] = [
        {'model_id':'EVENT.TEST'}, {'model_id':'ENCOUNTER.'+ids[1]},
        {'model_id':'ENCOUNTER.'+ids[2]}, {'model_id':'ENCOUNTER.UNKNOWN'}]
    origin = reconstruct(run, catalog)[1]
    targets, audit = window_for_origin(recorded_floors(run), origin, catalog)
    assert {t['id'] for t in targets} == set(ids)
    assert audit['skipped'] == [{'floor':3,'target':'UNKNOWN','reason':'Encounter not in the act catalog'}]


def test_migration_preserves_all_labels_attempts_and_sources_and_restores_new_source(run,catalog,tmp_path):
    legacy = Catalog(catalog.raw, {**catalog.config,'target_policy':'whole_act_v1'})
    store = Store(tmp_path/'queue.sqlite')
    import_run(store,legacy,{},run,'aa','fixture')
    # A historical completed job outside the new window remains byte-identical.
    row = store.db.execute("SELECT id FROM jobs WHERE json_extract(target,'$.id')=? LIMIT 1",
                           (catalog.acts['OVERGROWTH']['encounters'][1]['id'],)).fetchone()
    with store.db:
        store.db.execute("UPDATE jobs SET status='complete',attempts=1,result=? WHERE id=?", ('{"synthetic":true}',row[0]))
        store.db.execute("INSERT INTO attempts(job_id,status,result,finished) VALUES(?,'complete','synthetic-fixture',1)",(row[0],))
    before = preserved_hashes(store.db)
    preview = plan_window(store.db,catalog)['report']
    assert preview['selected_pairs']==2 and preview['selected_battles']==8
    assert preview['exclude_pending']>0
    with pytest.raises(ValueError,match='migrate'):
        require_policy(store,catalog.config)
    report = migrate_window(store,catalog,{})
    assert report['after_counts']['pending']==8
    assert report['after_counts']['complete']==1 and report['added']==0
    assert before == preserved_hashes(store.db)
    assert migrate_window(store,catalog,{})['exclude_pending']==0
    assert store.db.execute('SELECT count(*) FROM target_origins').fetchone()[0]==4
    # Same build appearing in a new source expands the union and revives only
    # its newly recorded targets. Re-importing cannot duplicate those jobs.
    newer = deepcopy(run)
    new_target = catalog.acts['OVERGROWTH']['encounters'][2]['id']
    newer['map_point_history'][0][2]['rooms']=[{'model_id':'ENCOUNTER.'+new_target}]
    result = import_run(store,catalog,{},newer,'bb','fixture')
    assert result['scheduled_now']==8
    assert store.counts()['pending']==16
    assert import_run(store,catalog,{},newer,'bb','fixture')['scheduled_now']==0
    for _ in range(16):
        job=store.claim()
        assert job['target']['id'] in {new_target,reconstruct(run,catalog)[1]['target']}
    assert store.claim() is None


@pytest.mark.parametrize('status', ['running','failed'])
def test_migration_refuses_undrained_or_failed_jobs(run,catalog,tmp_path,status):
    legacy = Catalog(catalog.raw,{**catalog.config,'target_policy':'whole_act_v1'})
    store=Store(tmp_path/'jobs.sqlite');import_run(store,legacy,{},run,'aa','fixture')
    with store.db:store.db.execute('UPDATE jobs SET status=? WHERE id=(SELECT id FROM jobs LIMIT 1)',(status,))
    before=list(map(tuple,store.db.execute('SELECT * FROM jobs ORDER BY id')))
    with pytest.raises(ValueError,match='Drain'):
        migrate_window(store,catalog,{})
    assert list(map(tuple,store.db.execute('SELECT * FROM jobs ORDER BY id')))==before


def test_invalid_origin_fails_before_queue_changes(run,catalog,tmp_path):
    legacy=Catalog(catalog.raw,{**catalog.config,'target_policy':'whole_act_v1'})
    store=Store(tmp_path/'jobs.sqlite');import_run(store,legacy,{},run,'aa','fixture')
    with store.db:store.db.execute("UPDATE build_origins SET details=json_set(details,'$.floor',999)")
    before=store.counts()
    with pytest.raises(ValueError,match='floor'):
        migrate_window(store,catalog,{})
    assert store.counts()==before
