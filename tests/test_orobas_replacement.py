"""Original-position replacement, native injection and source replay regressions."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import random

import pytest

from damage_model import run_import
from damage_model.catalog import Catalog
from damage_model.mutations import mutate
from damage_model.run_import import reconstruct, build_for, import_run
from damage_model.schema import Relic
from damage_model.starter_relics import SNAKE, DRAKE, TOUCH
from damage_model.store import Store
from damage_model.worker import request_for
from test_pipeline import observation
from test_run_import import run, catalog, node

ROOT = Path(__file__).resolve().parents[1]
REMOVED = {'ALCHEMICAL_COFFER', 'DELICATE_FROND', 'NEOWS_SACRIFICE', 'FUR_COAT', 'PAELS_TOOTH'}


def source_with_reward(source, catalog, reward, act):
    source = deepcopy(source)
    ancient = next(a for a, v in catalog.ancients.items() if reward in v['possible_relics'])
    if act == 1:
        stats = source['map_point_history'][0][0]['player_stats'][0]
        stats['ancient_choice'][0]['TextKey'] = reward
        stats['relic_choices'][0]['choice'] = 'RELIC.' + reward
        source['players'][0]['relics'][1]['id'] = 'RELIC.' + reward
        return source
    for number, act_id in ((2, 'HIVE'), (3, 'GLORY')):
        if number > act:
            break
        event, rid = (ancient, reward) if number == act else ('PAEL', 'PAELS_BLOOD')
        source['acts'].append('ACT.' + act_id)
        source['players'][0]['relics'].append({'id': 'RELIC.' + rid})
        source['map_point_history'].append([
            node('EVENT.' + event, ancient_choice=[{'TextKey': rid, 'was_chosen': True}],
                 relic_choices=[{'choice': 'RELIC.' + rid, 'was_picked': True}]),
            node('ENCOUNTER.' + catalog.acts[act_id]['encounters'][0]['id'])])
    return source


def orobas_source(source, catalog, through_act=2):
    source = source_with_reward(source, catalog, TOUCH, 2)
    stats = source['map_point_history'][1][0]['player_stats'][0]
    stats['relic_choices'].append({'choice': 'RELIC.' + DRAKE, 'was_picked': True})
    stats['relics_removed'] = ['RELIC.' + SNAKE]
    source['players'][0]['relics'][0]['id'] = 'RELIC.' + DRAKE
    source['players'][0]['relics'][-1]['props'] = {'model_ids': [
        {'name': 'StarterRelic', 'value': 'RELIC.' + SNAKE},
        {'name': 'UpgradedRelic', 'value': 'RELIC.' + DRAKE}]}
    if through_act == 3:
        source['acts'].append('ACT.GLORY')
        source['players'][0]['relics'].append({'id': 'RELIC.BLESSED_ANTLER'})
        source['map_point_history'].append([
            node('EVENT.NONUPEIPE', ancient_choice=[{'TextKey': 'BLESSED_ANTLER', 'was_chosen': True}],
                 relic_choices=[{'choice': 'RELIC.BLESSED_ANTLER', 'was_picked': True}]),
            node('ENCOUNTER.' + catalog.acts['GLORY']['encounters'][0]['id'])])
    return source


@pytest.mark.parametrize('through_act', [2, 3])
def test_source_replaces_in_original_position_and_native_request_replays_only_touch(run, catalog, through_act):
    source = orobas_source(run, catalog, through_act)
    states = reconstruct(source, catalog)
    assert states[2]['relics'][0] == SNAKE and TOUCH not in states[2]['relics']
    state = states[-1]
    assert state['relics'][0] == DRAKE and SNAKE not in state['relics']
    assert state['relics'] == tuple(x['id'][6:] for x in source['players'][0]['relics'])
    build, seed = build_for(state, 'run-a', catalog)
    assert build_for(state, 'run-b', catalog)[1] == seed
    request = request_for({'id': 'fixture', 'build': build.to_dict(), 'seed': 'seed',
                           'target': catalog.targets(build)[0]}, catalog.config)
    assert not {SNAKE, DRAKE} & {r['relicId'] for r in request['relics']}
    assert [r['relicId'] for r in request['relics'] if not r['addWithoutObtainedEffects']] == [TOUCH]
    assert [r['relicId'] for r in request['relics']] == [r.id for r in build.relics[1:]]
    assert request['potions'] == [] and request['potionPolicyForTest'] == 'Disabled'
    assert [(c['cardId'], c['upgradeLevels']) for c in request['runCards']] == [(c.id, c.upgrade) for c in build.cards]


@pytest.mark.parametrize('bad', ['missing_removal', 'missing_drake_gain', 'unpicked_touch', 'wrong_saved_upgrade', 'wrong_event', 'appended_drake'])
def test_inconsistent_replacement_history_is_rejected(run, catalog, bad):
    source = orobas_source(run, catalog)
    stats = source['map_point_history'][1][0]['player_stats'][0]
    if bad == 'missing_removal': stats['relics_removed'] = []
    elif bad == 'missing_drake_gain': stats['relic_choices'].pop()
    elif bad == 'unpicked_touch': stats['ancient_choice'][0]['was_chosen'] = False
    elif bad == 'wrong_saved_upgrade': source['players'][0]['relics'][-1]['props']['model_ids'][1]['value'] = 'RELIC.BLACK_BLOOD'
    elif bad == 'wrong_event': source['map_point_history'][1][0]['rooms'][0]['model_id'] = 'EVENT.PAEL'
    elif bad == 'appended_drake': source['players'][0]['relics'].append(source['players'][0]['relics'].pop(0))
    with pytest.raises(ValueError): reconstruct(source, catalog)


@pytest.mark.parametrize('bad', ['both_starters', 'no_touch', 'no_drake', 'wrong_history'])
def test_invalid_build_cannot_reach_native_request(run, catalog, bad):
    state = reconstruct(orobas_source(run, catalog), catalog)[-1]
    build, _ = build_for(state, 'source', catalog)
    if bad == 'both_starters': build = replace(build, relics=build.relics + (Relic(SNAKE),))
    elif bad == 'no_touch': build = replace(build, relics=tuple(r for r in build.relics if r.id != TOUCH))
    elif bad == 'no_drake': build = replace(build, relics=tuple(r for r in build.relics if r.id != DRAKE))
    elif bad == 'wrong_history': build = replace(build, ancient_history=build.ancient_history[:1])
    with pytest.raises(ValueError): catalog.validate(build)
    with pytest.raises(ValueError): request_for({'id': 'bad', 'build': build.to_dict()}, catalog.config)


@pytest.mark.parametrize('rid,act', [('ALCHEMICAL_COFFER', 2), ('DELICATE_FROND', 3), ('NEOWS_SACRIFICE', 1), ('FUR_COAT', 3), ('PAELS_TOOTH', 2)])
def test_newly_removed_relics_keep_the_source_build_and_ancient_history(run, catalog, rid, act):
    source = source_with_reward(run, catalog, rid, act)
    state = reconstruct(source, catalog)[-1]
    build, _ = build_for(state, 'source', catalog)
    assert rid not in [r.id for r in build.relics]
    assert build.ancient_history == state['ancient_history']
    assert [(c.id, c.upgrade) for c in build.cards] == [(c, u) for c, u, _ in state['cards']]
    with pytest.raises(ValueError, match='ancient provenance'):
        build_for({**state, 'relics': tuple(r for r in state['relics'] if r != rid)}, 'bad', catalog)
    assert {k for k in ('SEA_GLASS', 'TOY_BOX', 'PRISMATIC_GEM', 'KALEIDOSCOPE') if k in catalog.relic_pool} == set()


@pytest.mark.parametrize('revision', [run_import.PREVIOUS_IMPORT_REVISION, run_import.SHARED_ANCIENT_REVISION, run_import.REMOVED_RELIC_REVISION])
@pytest.mark.parametrize('kind', ['replacement', 'removal'])
def test_old_sources_reaudit_idempotently_without_rewriting_labels(run, catalog, tmp_path, monkeypatch, revision, kind):
    source = orobas_source(run, catalog) if kind == 'replacement' else source_with_reward(run, catalog, 'FUR_COAT', 3)
    old = Catalog(catalog.raw, {**catalog.config, 'removed_relic_ids': sorted(set(catalog.config['removed_relic_ids']) - REMOVED)})
    store = Store(tmp_path/'jobs.sqlite')
    with monkeypatch.context() as patch:
        patch.setattr(run_import, 'IMPORT_REVISION', revision)
        import_run(store, old, {}, run, 'baseline', 'original')
        if kind == 'replacement':
            # Use the original rejection type caught by the importer.
            def old_reconstruct(*args): raise run_import.RunRejected('Reconstructed final relic order/inventory does not match the run')
            patch.setattr(run_import, 'reconstruct', old_reconstruct)
        previous = import_run(store, old, {}, source, 'affected', 'original')
    job = store.claim(); assert store.finish(job, observation(job)) == 'complete'
    saved = tuple(store.db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone())
    attempts = [tuple(r) for r in store.db.execute('SELECT * FROM attempts')]
    revised = import_run(store, catalog, {}, source, 'affected', 'new-url')
    assert revised['version'] == run_import.IMPORT_REVISION and revised['scheduled_now'] > 0
    assert revised['accepted_floors'] > previous['accepted_floors']
    assert tuple(store.db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone()) == saved
    assert [tuple(r) for r in store.db.execute('SELECT * FROM attempts')] == attempts
    history = store.db.execute('SELECT version,report FROM source_import_history WHERE hash=?', ('affected',)).fetchone()
    assert history['version'] == revision and json.loads(history['report']) == previous
    assert import_run(store, catalog, {}, source, 'affected', 'url')['scheduled_now'] == 0
    assert import_run(store, catalog, {}, run, 'baseline', 'url')['scheduled_now'] == 0


def test_mutations_keep_drake_and_touch(run, catalog):
    parent, _ = build_for(reconstruct(orobas_source(run, catalog), catalog)[-1], 'source', catalog)
    policy = json.loads((ROOT/'configs/mutations-8s.json').read_text())
    for seed in range(8):
        result = mutate(parent, catalog, random.Random(seed), 'large', 'both', policy)
        if result is None: continue
        child = result[0]
        assert child.relics[0].id == DRAKE and any(r.id == TOUCH for r in child.relics)
        catalog.validate(child)
