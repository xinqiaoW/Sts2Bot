"""Old-source inventories must become valid current requests without changing labels."""
from copy import deepcopy
import json

import pytest

from damage_model.run_import import check_run, reconstruct, import_run, build_for, source_checksum, RunRejected
from damage_model.source_versions import SOURCE_SCHEMAS, COMPATIBILITY_REVISION, normalize_history
from damage_model.schema import canonical
from damage_model.store import Store
from damage_model.worker import request_for
from test_run_import import catalog, run, node


@pytest.mark.parametrize('version,schema', SOURCE_SCHEMAS.items())
def test_explicit_versions_keep_all_original_admission_rules(run, version, schema):
    run.update(build_id=version, schema_version=schema)
    check_run(run)
    for patch in ({'schema_version': 8}, {'ascension': 9}, {'modifiers': ['modifier']},
                  {'players': run['players'] * 2}, {'build_id': 'v0.108.0'}, {'build_id': 'v0.112.0'}):
        with pytest.raises(RunRejected):
            check_run({**run, **patch})


@pytest.mark.parametrize('version', ['v0.109.0', 'v0.109.1'])
def test_scare_gain_upgrade_enchant_and_final_deck_become_sidestep(run, catalog, tmp_path, version):
    run.update(build_id=version, schema_version=9)
    gain = run['map_point_history'][0][1]['player_stats'][0]['cards_gained'][0]
    gain['id'] = 'CARD.SCARE'
    final = run['players'][0]['deck'][-1]
    final.update(id='CARD.SCARE', current_upgrade_level=1,
                 enchantment={'id': 'ENCHANTMENT.NIMBLE', 'amount': 2})
    third = run['map_point_history'][0][2]['player_stats'][0]
    third['upgraded_cards'] = ['CARD.SCARE']
    third['cards_enchanted'] = [{'card': deepcopy(final), 'enchantment': 'ENCHANTMENT.NIMBLE'}]
    run['map_point_history'][0].append(node(run['map_point_history'][0][2]['rooms'][0]['model_id']))
    before = canonical(run)
    snapshot = reconstruct(run, catalog)[-1]
    build, _ = build_for(snapshot, 'aa', catalog)
    assert [(c.id, c.upgrade, c.enchantment_id, c.enchantment_amount) for c in build.cards if c.id == 'SIDESTEP'] == [('SIDESTEP', 1, 'NIMBLE', 2)]
    assert canonical(run) == before
    with_store = Store(tmp_path/'jobs.sqlite')
    try:
        report = import_run(with_store, catalog, {}, run, 'aa', 'fixture')
        assert report['accepted_floors'] == 3 and report['version'] == COMPATIBILITY_REVISION
        row = with_store.db.execute('select * from source_runs').fetchone()
        assert row['body'] == before and row['sha256'] == source_checksum(run)
        details = json.loads(with_store.db.execute('select details from build_origins where floor=4').fetchone()[0])
        assert details['source_compatibility']['card_aliases'] == {'SCARE': 'SIDESTEP'}
        job = next(dict(j) for j in with_store.db.execute('select * from jobs') if j['build_id'] == build.id)
        job.update(build=build.to_dict(), target=json.loads(job['target']))
        request = request_for(job, catalog.config)
        assert not any(c['cardId'] == 'SCARE' for c in request['runCards'])
        assert {'cardId': 'SIDESTEP', 'upgradeLevels': 1, 'count': 1,
                'enchantmentId': 'NIMBLE', 'enchantmentAmount': 2} in request['runCards']
        assert import_run(with_store, catalog, {}, run, 'aa', 'fixture')['scheduled_now'] == 0
    finally:
        with_store.db.close()


def test_conversion_covers_transform_remove_downgrade_and_preserves_unknown_state():
    card = {'id': 'CARD.SCARE', 'current_upgrade_level': 1, 'floor_added_to_deck': 5, 'props': {'unknown': 12}}
    raw = {'build_id': 'v0.109.0', 'schema_version': 9, 'username': 'CARD.SCARE', 'players': [{'deck': [card]}],
           'map_point_history': [[{'player_stats': [{'cards_transformed': [{'original_card': card, 'final_card': card}],
              'cards_removed': [card], 'downgraded_cards': ['CARD.SCARE']}]}]]}
    changed = normalize_history(raw)
    assert changed['username'] == 'CARD.SCARE' and changed['build_id'] == 'v0.109.0'
    assert changed['players'][0]['deck'][0] == {**card, 'id': 'CARD.SIDESTEP'}
    assert 'CARD.SCARE' not in canonical(changed['map_point_history'])
    assert raw['players'][0]['deck'][0]['id'] == 'CARD.SCARE'
    for version in ('v0.110.0', 'v0.111.0', 'v0.108.0'):
        assert normalize_history({**raw, 'build_id': version})['players'][0]['deck'][0]['id'] == 'CARD.SCARE'


def test_old_versions_deduplicate_current_jobs_and_preserve_completed_quarantined_rows(run, catalog, tmp_path):
    store = Store(tmp_path/'jobs.sqlite')
    try:
        import_run(store, catalog, {}, run, 'aa', 'fixture')
        ids = [r[0] for r in store.db.execute('select id from jobs order by id')]
        store.db.execute("update jobs set status='complete',result='original label',attempts=1 where id=?", (ids[0],))
        store.db.execute("update jobs set status='quarantined',result='original failure',attempts=3 where id=?", (ids[1],))
        store.db.commit()
        before = list(map(tuple, store.db.execute('select * from jobs order by id')))
        current = tuple(store.db.execute('select * from source_runs where hash="aa"').fetchone())
        for i, (version, schema) in enumerate(SOURCE_SCHEMAS.items()):
            report = import_run(store, catalog, {}, {**run, 'build_id': version, 'schema_version': schema}, 'old'+str(i), 'fixture')
            assert report['accepted_floors'] == 2 and report['scheduled_now'] == 0
        assert before == list(map(tuple, store.db.execute('select * from jobs order by id')))
        import_run(store, catalog, {}, run, 'aa', 'fixture')
        assert current == tuple(store.db.execute('select * from source_runs where hash="aa"').fetchone())
    finally:
        store.db.close()
