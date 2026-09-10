"""Synthetic run histories only; no synthetic battle label enters collection."""
from copy import deepcopy
import json

import pytest

from damage_model.catalog import Catalog
from damage_model import run_import
from damage_model.run_import import build_for, reconstruct, import_run
from damage_model.store import Store
from damage_model.worker import request_for
from test_run_import import catalog, run, node
from test_pipeline import observation


def with_darv(run, catalog, act, reward='RUNIC_PYRAMID'):
    source = deepcopy(run)
    for number, act_id in ((2, 'HIVE'), (3, 'GLORY')):
        if number > act:
            break
        ancient, relic = ('DARV', reward) if number == act else ('PAEL', 'PAELS_BLOOD')
        source['acts'].append('ACT.' + act_id)
        source['players'][0]['relics'].append({'id': 'RELIC.' + relic})
        target = catalog.acts[act_id]['encounters'][0]['id']
        source['map_point_history'].append([
            node('EVENT.' + ancient, ancient_choice=[{'TextKey': relic, 'was_chosen': True}],
                 relic_choices=[{'choice': 'RELIC.' + relic, 'was_picked': True}]),
            node('ENCOUNTER.' + target)])
    return source


@pytest.mark.parametrize('act', [2, 3])
@pytest.mark.parametrize('reward', ['ASTROLABE', 'BLACK_STAR', 'CALLING_BELL', 'DUSTY_TOME',
    'ECTOPLASM', 'EMPTY_CAGE', 'PANDORAS_BOX', 'PHILOSOPHERS_STONE', 'RUNIC_PYRAMID',
    'SOZU', 'VELVET_CHOKER', 'SNECKO_EYE'])
def test_real_shared_source_and_pickup_normalization(run, catalog, act, reward):
    assert catalog.shared_ancients == {'DARV'}
    assert all('DARV' not in a['ancients'] for a in catalog.acts.values())
    source = with_darv(run, catalog, act, reward)
    state = reconstruct(source, catalog)[-1]
    build, _ = build_for(state, 'source', catalog)
    assert build.ancient_history[-1] == (act, 'DARV', reward)
    assert (reward in [r.id for r in build.relics]) == (reward != 'SNECKO_EYE')
    request = request_for({'id': 'synthetic', 'build': build.to_dict(), 'seed': 's',
                          'target': catalog.targets(build)[0]}, catalog.config)
    assert all(r['addWithoutObtainedEffects'] for r in request['relics'])
    assert [c['cardId'] for c in request['runCards']] == [c.id for c in build.cards]


def test_shared_history_still_rejects_first_act_repeat_wrong_reward_missing_inventory(run, catalog):
    state = reconstruct(with_darv(run, catalog, 2), catalog)[-1]
    cases = [
        (1, ((1, 'DARV', 'RUNIC_PYRAMID'),), state['relics'], 'Illegal ancient provenance'),
        (3, (*state['ancient_history'], (3, 'DARV', 'BLACK_STAR')),
         (*state['relics'], 'BLACK_STAR'), 'only once'),
        (2, (state['ancient_history'][0], (2, 'DARV', 'PAELS_BLOOD')),
         (*state['relics'], 'PAELS_BLOOD'), 'Illegal ancient provenance'),
        (2, state['ancient_history'], tuple(r for r in state['relics'] if r != 'RUNIC_PYRAMID'),
         'Illegal ancient provenance'),
        (2, ((1, 'NEOW', 'POMANDER'), (3, 'DARV', 'RUNIC_PYRAMID')),
         state['relics'], 'exactly'),
        (2, ((1, 'NEOW', 'POMANDER'), (2, 'UNKNOWN', 'RUNIC_PYRAMID')),
         state['relics'], 'Illegal ancient provenance'),
    ]
    for act, history, relics, error in cases:
        with pytest.raises(ValueError, match=error):
            catalog.validate_ancient_history(act, history, relics)


def test_shared_does_not_relax_normal_ancients_or_unknown_catalog(run, catalog):
    state = reconstruct(with_darv(run, catalog, 2), catalog)[-1]
    with pytest.raises(ValueError, match='Illegal ancient provenance'):
        catalog.validate_ancient_history(2,
            (state['ancient_history'][0], (2, 'TANX', 'SAI')), (*state['relics'], 'SAI'))
    with pytest.raises(ValueError, match='Unknown shared ancient'):
        Catalog({**catalog.raw, 'shared_ancients': ['UNKNOWN']}, catalog.config)
    old = Catalog({k: v for k, v in catalog.raw.items() if k != 'shared_ancients'}, catalog.config)
    with pytest.raises(ValueError, match='Illegal ancient provenance'):
        build_for(state, 'source', old)


def test_v4_reaudit_preserves_old_jobs_attempts_source_and_counter_state(run, catalog, tmp_path, monkeypatch):
    catalog = Catalog(catalog.raw, {**catalog.config, 'target_policy': 'source_floor_window_v1',
                                   'target_floor_radius': 2})
    source = with_darv(run, catalog, 3)
    old_catalog = Catalog({**catalog.raw, 'shared_ancients': []}, catalog.config)
    store = Store(tmp_path/'labels.sqlite')
    with monkeypatch.context() as patch:
        patch.setattr(run_import, 'IMPORT_REVISION', run_import.PREVIOUS_IMPORT_REVISION)
        before_report = import_run(store, old_catalog, {}, source, 'source', 'original-url')
    assert before_report['skipped']['Illegal ancient provenance'] == 1
    job = store.claim()
    assert store.finish(job, observation(job)) == 'complete'
    before_jobs = list(map(tuple, store.db.execute('SELECT * FROM jobs ORDER BY id')))
    before_attempts = list(map(tuple, store.db.execute('SELECT * FROM attempts ORDER BY id')))
    before_builds = list(map(tuple, store.db.execute('SELECT * FROM builds ORDER BY id')))
    before_source = tuple(store.db.execute('SELECT hash,sha256,source,body FROM source_runs').fetchone())
    report = import_run(store, catalog, {}, source, 'source', 'same-payload-new-url')
    assert report['accepted_floors'] == before_report['accepted_floors'] + 1
    assert report['scheduled_now'] == 4
    assert report['version'] == run_import.IMPORT_REVISION
    for row in before_jobs:
        assert tuple(store.db.execute('SELECT * FROM jobs WHERE id=?', (row[0],)).fetchone()) == row
    assert list(map(tuple, store.db.execute('SELECT * FROM attempts ORDER BY id'))) == before_attempts
    for row in before_builds:
        assert tuple(store.db.execute('SELECT * FROM builds WHERE id=?', (row[0],)).fetchone()) == row
    assert tuple(store.db.execute('SELECT hash,sha256,source,body FROM source_runs').fetchone()) == before_source
    history = store.db.execute('SELECT version,report FROM source_import_history').fetchone()
    assert history['version'] == run_import.PREVIOUS_IMPORT_REVISION
    assert json.loads(history['report']) == before_report
    assert import_run(store, catalog, {}, source, 'source', 'url', reprocess=True)['scheduled_now'] == 0
    store.db.close()


def test_unaffected_v4_source_stays_idempotent_and_unknown_revisions_fail(run, catalog, tmp_path, monkeypatch):
    store = Store(tmp_path/'labels.sqlite')
    with monkeypatch.context() as patch:
        patch.setattr(run_import, 'IMPORT_REVISION', run_import.PREVIOUS_IMPORT_REVISION)
        import_run(store, catalog, {}, run, 'source', 'url')
    before = tuple(store.db.execute('SELECT * FROM source_runs').fetchone())
    assert import_run(store, catalog, {}, run, 'source', 'url')['scheduled_now'] == 0
    assert tuple(store.db.execute('SELECT * FROM source_runs').fetchone()) == before
    with store.db:
        store.db.execute("UPDATE source_runs SET version='unknown_future'")
    with pytest.raises(ValueError, match='explicitly reprocess'):
        import_run(store, catalog, {}, run, 'source', 'url', reprocess=True)
    store.db.close()
