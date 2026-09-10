from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import json
import numpy as np
import pytest

from damage_model.catalog import Catalog, COUNTER_DOMAINS, IMPORTED_COUNTER_DOMAINS, validate_counter_relation
from damage_model.encoding import Encoder
from damage_model.run_import import HistoryCard, apply_floor, import_card, build_for, reconstruct
from damage_model.schema import Card, Build, Relic, digest
from damage_model.store import Store
from damage_model.worker import request_for
from test_run_import import run, catalog
from test_pipeline import observation


def test_card_identity_keeps_enchantment_on_its_copy_and_preserves_old_ids(run, catalog):
    b, _ = build_for(reconstruct(run,catalog)[1], 'a', catalog)
    assert b.id == digest({**b.state(), 'cards':[{'id':c.id,'upgrade':c.upgrade} for c in sorted(b.cards)]})
    a = replace(b, cards=b.cards+(Card('BACKFLIP',0,'NIMBLE',2),Card('BACKFLIP',1)))
    swapped = replace(b, cards=b.cards+(Card('BACKFLIP',0),Card('BACKFLIP',1,'NIMBLE',2)))
    assert a.id != swapped.id and Build.from_dict(a.to_dict()) == a
    assert replace(a,cards=tuple(reversed(a.cards))).id == a.id
    target=catalog.targets(b)[0]['id'];encoder=Encoder.from_catalog(catalog)
    assert not np.array_equal(encoder.encode(a,target,70),encoder.encode(swapped,target,70))
    changed=replace(a,cards=b.cards+(Card('BACKFLIP',0,'NIMBLE',3),Card('BACKFLIP',1)))
    assert not np.array_equal(encoder.encode(a,target,70),encoder.encode(changed,target,70))
    legacy=Encoder({'features':[k for k in encoder.spec['features'] if not k.startswith('enchanted:')]})
    with pytest.raises(ValueError,match='Unknown model feature'): legacy.encode(a,target,70)


def test_enchantment_request_and_native_mismatch_rejection(run,catalog,tmp_path):
    b,_=build_for(reconstruct(run,catalog)[1], 'a', catalog)
    b=replace(b,cards=b.cards+(Card('BACKFLIP',1,'NIMBLE',2),))
    catalog.validate(b)
    s=Store(tmp_path/'jobs.sqlite');s.schedule(b,catalog.targets(b)[:1],['one'],{})
    job=s.claim();request=request_for(job,catalog.config)
    enchanted=[c for c in request['runCards'] if c.get('enchantmentId')]
    assert enchanted==[{'cardId':'BACKFLIP','upgradeLevels':1,'count':1,'enchantmentId':'NIMBLE','enchantmentAmount':2}]
    result=observation(job)
    with pytest.raises(ValueError,match='starting deck'):s.finish(job,result)
    card=result['trainingObservation']['initialBuild']['cards'][-1]
    card.update(enchantmentId='NIMBLE',enchantmentAmount=3)
    with pytest.raises(ValueError,match='starting deck'):s.finish(job,result)
    card['enchantmentAmount']=2
    assert s.finish(job,result)=='complete'


def test_history_enchantment_retains_instance_and_does_not_double_apply(catalog):
    record={'card':{'id':'CARD.BACKFLIP','floor_added_to_deck':2,
                   'enchantment':{'id':'ENCHANTMENT.NIMBLE','amount':2}},'enchantment':'ENCHANTMENT.NIMBLE'}
    deck=(HistoryCard('BACKFLIP',0,1),HistoryCard('BACKFLIP',0,2))
    outcome=apply_floor(deck,{'cards_enchanted':[record]},3,catalog)
    assert len(outcome)==1
    after=next(iter(outcome));assert after[0].extra=='{}' and after[1].extra!='{}'
    assert apply_floor(after,{'cards_enchanted':[record]},3,catalog)==outcome
    assert import_card(after[1].id,after[1].upgrade,after[1].extra)==Card('BACKFLIP',0,'NIMBLE',2)
    for extra in ['{"enchantment":{"id":"ENCHANTMENT.NIMBLE","amount":true}}',
                  '{"enchantment":{"id":"ENCHANTMENT.NIMBLE","amount":0}}',
                  '{"enchantment":{"id":"ENCHANTMENT.NIMBLE","amount":1,"unknown":2}}']:
        with pytest.raises(ValueError):import_card('BACKFLIP',0,extra)


def test_import_enchanted_floor_is_after_the_enchant_event(run,catalog):
    record={'card':{'id':'CARD.NEUTRALIZE','current_upgrade_level':1,'floor_added_to_deck':1,
                   'enchantment':{'id':'ENCHANTMENT.SHARP','amount':3}},'enchantment':'ENCHANTMENT.SHARP'}
    run['map_point_history'][0][1]['player_stats'][0]['cards_enchanted']=[record]
    next(c for c in run['players'][0]['deck'] if c['id']=='CARD.NEUTRALIZE')['enchantment']=record['card']['enchantment']
    states=reconstruct(run,catalog)
    before,_=build_for(states[1],'a',catalog);after,_=build_for(states[2],'a',catalog)
    assert not any(c.enchantment_id for c in before.cards)
    assert Card('NEUTRALIZE',1,'SHARP',3) in after.cards


def test_all_ordinary_counter_fields_are_adapted_with_real_types(catalog):
    for rid, domains in IMPORTED_COUNTER_DOMAINS.items():
        assert rid in catalog.relic_pool
        native={p['name']:p['type'] for p in catalog.relics[rid]['state_properties']}
        assert set(native)==set(domains)
        for key,values in domains.items():
            assert all(type(v) is (bool if native[key]=='Boolean' else int) for v in values)
    with pytest.raises(ValueError):validate_counter_relation('WONGOS_MYSTERY_TICKET',{'CombatsFinished':0,'GaveRelic':True})
    assert COUNTER_DOMAINS['SWORD_OF_STONE']['ElitesDefeated']==list(range(5))
    # Toy Box also requires other relics' wax/melt state, not just its scalar counter.
    assert 'TOY_BOX' not in catalog.relic_pool


def test_counter_samples_and_encoding_are_fixed_per_inventory(run,catalog):
    state=reconstruct(run,catalog)[1];state['relics']+=('PENDULUM','WONGOS_MYSTERY_TICKET')
    a,_=build_for(state,'a',catalog);b,_=build_for(state,'b',catalog)
    assert a.id==b.id and a.relics==b.relics
    ticket=dict(a.relics[-1].state);assert ticket['GaveRelic']==(ticket['CombatsFinished']>=5)
    changed=replace(a,relics=a.relics[:-2]+(Relic('PENDULUM',(('TurnsSeen',(dict(a.relics[-2].state)['TurnsSeen']+1)%3),)),a.relics[-1]))
    encoder=Encoder.from_catalog(catalog);target=catalog.targets(a)[0]['id']
    assert not np.array_equal(encoder.encode(a,target,70),encoder.encode(changed,target,70))
