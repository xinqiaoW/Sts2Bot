from dataclasses import replace
import json

import pytest

from damage_model.run_import import build_for, reconstruct, import_run
from damage_model.schema import Relic
from damage_model.store import Store
from damage_model.worker import request_for
from test_run_import import run, catalog


@pytest.mark.parametrize('rid', ['SNECKO_EYE', 'FAKE_SNECKO_EYE', 'MASSIVE_SCROLL',
                                'PAELS_EYE', 'GOLDEN_COMPASS'])
def test_user_removal_preserves_cards_counters_and_source_provenance(run, catalog, rid):
    state = reconstruct(run, catalog)[1]
    state['relics'] += ('PEN_NIB',)
    if catalog.relics[rid]['rarity'] == 'Ancient':
        reachable = {a for spec in catalog.acts.values() for a in spec['ancients']} | catalog.shared_ancients
        ancient = next(a for a in catalog.ancients if a in reachable and rid in catalog.ancients[a]['possible_relics'])
        act = next(a for a in catalog.acts.values() if ancient in a['ancients']
                   or (a['act'] > 1 and ancient in catalog.shared_ancients))
        # Retain the real first-act history and attach the later-act choice.
        for i in range(2, act['act']):
            intermediate = next(a for a in catalog.acts.values() if a['act'] == i)
            giver = intermediate['ancients'][0]
            reward = next(r for r in catalog.ancients[giver]['possible_relics'] if r in catalog.relic_pool)
            state['ancient_history'] += ((i, giver, reward),)
            state['relics'] += (reward,)
        if act['act'] == 1:
            state['relics'] = tuple(r for r in state['relics'] if r != state['ancient_history'][0][2])
            state['ancient_history'] = ()
        state.update(act=act['act'], act_id=act['id'], target=act['encounters'][0]['id'])
        state['ancient_history'] += ((act['act'], ancient, rid),)
    state['relics'] += (rid,)
    state['cards'] += (('BACKFLIP', 1, json.dumps({'enchantment': {'id': 'ENCHANTMENT.SWIFT', 'amount': 1}})),)
    build, seed = build_for(state, 'real-test', catalog)
    assert rid not in {r.id for r in build.relics}
    assert build.cards[-1].upgrade == 1 and build.cards[-1].enchantment_id == 'SWIFT'
    assert build.ancient_history == state['ancient_history']
    assert build_for(state, 'another-source', catalog)[1] == seed
    request = request_for({'id': 'test', 'build': build.to_dict(), 'seed':'test',
                           'target':catalog.targets(build)[0]}, catalog.config)
    assert all(r['relicId'] != rid for r in request['relics'])
    with pytest.raises(ValueError, match='Disallowed relic'):
        catalog.validate(replace(build, relics=build.relics + (Relic(rid),)))
    if catalog.relics[rid]['rarity'] == 'Ancient':
        with pytest.raises(ValueError, match='ancient provenance'):
            build_for({**state, 'relics':tuple(r for r in state['relics'] if r != rid)}, 'bad', catalog)


def test_neows_bones_only_explains_two_neow_rewards(run, catalog):
    state = reconstruct(run, catalog)[1]
    state['ancient_history'] = ((1, 'NEOW', 'NEOWS_BONES'),)
    state['relics'] = ('RING_OF_THE_SNAKE', 'NEOWS_BONES', 'NEW_LEAF', 'ARCANE_SCROLL')
    build, _ = build_for(state, 'source', catalog)
    assert len(build.relics) == 4
    for extra in ('JEWELRY_BOX', 'LOST_COFFER'):
        with pytest.raises(ValueError, match='acquisition history'):
            build_for({**state, 'relics':state['relics'] + (extra,)}, 'bad', catalog)
    # Removed max-HP rewards must still count in the original source inventory.
    with pytest.raises(ValueError, match='acquisition history'):
        build_for({**state, 'relics':state['relics'] + ('LEAFY_POULTICE',)}, 'bad', catalog)
    with pytest.raises(ValueError, match='acquisition history'):
        build_for({**state, 'ancient_history':((1, 'NEOW', 'NEW_LEAF'),),
                   'relics':('RING_OF_THE_SNAKE', 'NEW_LEAF', 'ARCANE_SCROLL')}, 'bad', catalog)


def test_reimport_v3_preserves_history_and_separates_removal_reasons(run, catalog, tmp_path):
    # An ordinary user-removed item and max-HP item must not be conflated.
    stats = run['map_point_history'][0][1]['player_stats'][0]
    stats['relic_choices'] = [{'choice':'RELIC.'+r,'was_picked':True} for r in ('FAKE_SNECKO_EYE','STRAWBERRY')]
    run['players'][0]['relics'] += [{'id':'RELIC.'+r} for r in ('FAKE_SNECKO_EYE','STRAWBERRY')]
    store = Store(tmp_path/'test.sqlite')
    report = import_run(store,catalog,{},run,'hash','test')
    assert report['removed_user_relics'] == {'FAKE_SNECKO_EYE':1}
    assert report['removed_max_hp_relics'] == {'STRAWBERRY':1}
    with store.db:
        store.db.execute('UPDATE source_runs SET version=?', ('max_hp_relic_normalization_v3',))
        store.db.execute('INSERT INTO source_import_history VALUES(?,?,?,?)', ('hash','enchantments_counters_v2','{}',0))
    jobs = list(map(tuple,store.db.execute('SELECT * FROM jobs ORDER BY id')))
    second = import_run(store,catalog,{},run,'hash','test',reprocess=True)
    assert second['scheduled_now'] == 0
    assert list(map(tuple,store.db.execute('SELECT * FROM jobs ORDER BY id'))) == jobs
    assert store.db.execute('SELECT count(*) FROM source_import_history').fetchone()[0] == 2
    details = [json.loads(r[0]) for r in store.db.execute('SELECT details FROM build_origins')]
    assert any(d['normalization']['removed_user_relics'] == ['FAKE_SNECKO_EYE'] and
               d['normalization']['removed_max_hp_relics'] == ['STRAWBERRY'] for d in details)


def test_unadapted_gameplay_state_still_blocks_builds(catalog):
    assert all(r in catalog.relic_pool for r in ('NEW_LEAF','DUSTY_TOME','BYRDPIP','PAELS_LEGION',
                                                'BELT_BUCKLE','BIIIG_HUG','BLOOD_SOAKED_ROSE'))
    assert all(r not in catalog.relic_pool for r in ('FUR_COAT','PAELS_TOOTH','SEA_GLASS','TOUCH_OF_OROBAS','TOY_BOX'))
