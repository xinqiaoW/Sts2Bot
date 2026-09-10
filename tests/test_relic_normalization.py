from dataclasses import replace
import json

import pytest

from damage_model.catalog import Catalog
from damage_model.run_import import build_for, reconstruct, import_run
from damage_model.schema import Card, Relic
from damage_model.store import Store
from damage_model.worker import request_for
from test_run_import import run, catalog
from test_pipeline import observation


def test_remove_max_hp_relics_preserves_remaining_inventory_and_counters(run, catalog):
    state = reconstruct(run, catalog)[1]
    state['relics'] += ('PEN_NIB',)
    original, seed = build_for(state, 'aa', catalog)
    richer = {**state, 'relics': state['relics'] + ('STRAWBERRY', 'PEAR')}
    normalized, normalized_seed = build_for(richer, 'bb', catalog)
    assert normalized.id == original.id and normalized_seed == seed
    assert normalized.cards == original.cards and normalized.relics == original.relics
    assert all(r.id not in catalog.max_hp_relic_ids for r in normalized.relics)
    request = request_for({'id': 'fixture', 'build': normalized.to_dict(), 'seed': 'one',
                          'target': catalog.targets(normalized)[0]}, catalog.config)
    assert [r['relicId'] for r in request['relics']] == [r.id for r in original.relics
                                                    if r.id != 'RING_OF_THE_SNAKE']
    # Directly submitting an unnormalized build is still invalid.
    with pytest.raises(ValueError, match='Disallowed relic'):
        catalog.validate(replace(normalized, relics=normalized.relics + (Relic('STRAWBERRY'),)))


def test_removed_ancient_relic_keeps_real_provenance(run, catalog):
    state = reconstruct(run, catalog)[1]
    ancient_relic = next(r for r in catalog.ancients['NEOW']['possible_relics']
                        if r in catalog.max_hp_relic_ids)
    state['ancient_history'] = ((1, 'NEOW', ancient_relic),)
    state['relics'] = ('RING_OF_THE_SNAKE', ancient_relic)
    normalized, _ = build_for(state, 'aa', catalog)
    assert [r.id for r in normalized.relics] == ['RING_OF_THE_SNAKE']
    assert normalized.ancient_history == state['ancient_history']
    # An unrelated max-HP item cannot excuse a missing original ancient reward.
    bad = {**state, 'relics': ('RING_OF_THE_SNAKE', 'STRAWBERRY')}
    with pytest.raises(ValueError, match='ancient provenance'):
        build_for(bad, 'aa', catalog)


def test_ancient_cards_kept_with_upgrades_and_real_scope(run, catalog):
    state = reconstruct(run, catalog)[1]
    state['cards'] += (('APOTHEOSIS', 1, '{}'), ('SUPPRESS', 0, '{}'),
                       ('NEOWS_FURY', 0, '{}'))
    build, _ = build_for(state, 'aa', catalog)
    assert {Card('APOTHEOSIS', 1), Card('SUPPRESS'), Card('NEOWS_FURY')} <= set(build.cards)
    assert all(c.id not in catalog.excluded['cards'] for c in build.cards)
    assert 'DARK_EMBRACE' in catalog.excluded['cards']
    assert 'LIZARD_TAIL' in catalog.excluded['relics']
    assert 'NEW_LEAF' in catalog.relic_pool
    for rid in ('JEWELRY_BOX', 'NEOWS_TORMENT', 'ARCHAIC_TOOTH'):
        assert rid in catalog.relic_pool
    assert 'DUSTY_TOME' in catalog.relic_pool
    assert 'PAELS_TOOTH' not in catalog.relic_pool


def test_explicit_reprocess_preserves_labels_and_prior_report(run, catalog, tmp_path):
    old_config = {**catalog.config, 'max_hp_relic_policy': 'reject_build'}
    old_catalog = Catalog(catalog.raw, old_config)
    run['map_point_history'][0][1]['player_stats'][0]['relic_choices'] = [
        {'choice': 'RELIC.STRAWBERRY', 'was_picked': True}]
    run['players'][0]['relics'].append({'id': 'RELIC.STRAWBERRY'})
    run['map_point_history'][0][1]['player_stats'][0]['cards_gained'] = [
        {'id': 'CARD.BACKFLIP'}]
    store = Store(tmp_path / 'jobs.sqlite')
    old_report = import_run(store, old_catalog, {}, run, 'aa', 'fixture')
    assert old_report['accepted_floors'] == 1
    job = store.claim(); result = observation(job); assert store.finish(job, result) == 'complete'
    saved = tuple(store.db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone())
    with store.db:
        store.db.execute('UPDATE source_runs SET version=?', ('enchantments_counters_v2',))
    with pytest.raises(ValueError, match='explicitly reprocess'):
        import_run(store, catalog, {}, run, 'aa', 'fixture')
    revised = import_run(store, catalog, {}, run, 'aa', 'fixture', reprocess=True)
    assert revised['accepted_floors'] == 2 and revised['normalized_floors'] == 1
    assert revised['removed_max_hp_relics'] == {'STRAWBERRY': 1}
    assert tuple(store.db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone()) == saved
    history = store.db.execute('SELECT version,report FROM source_import_history').fetchone()
    assert history['version'] == 'enchantments_counters_v2' and json.loads(history['report']) == old_report
    assert import_run(store, catalog, {}, run, 'aa', 'fixture')['scheduled_now'] == 0
    body = json.loads(store.db.execute('SELECT body FROM source_runs').fetchone()[0])
    assert body == run
    origins = [json.loads(r[0]) for r in store.db.execute('SELECT details FROM build_origins')]
    assert any(o['normalization']['removed_max_hp_relics'] == ['STRAWBERRY'] for o in origins)
