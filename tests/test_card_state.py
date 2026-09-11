from dataclasses import replace
import json
import pytest

from damage_model.card_state import normalize_state, parse_props, state_props
from damage_model.schema import Card, Build, Relic, canonical, digest
from damage_model.catalog import Catalog
from damage_model.encoding import Encoder
from damage_model.observation import validate_cards
from damage_model.run_import import (HistoryCard, import_card, enter_history_floor,
                                     leave_history_combat, reconstruct)


@pytest.fixture
def catalog():
    return Catalog.load('catalogs/game-0.111.0.raw.json', 'configs/real-runs-8s.json')


def test_legacy_identity_and_saved_card_roundtrip():
    card = Card('BACKFLIP', 1)
    assert card.to_dict() == {'id': 'BACKFLIP', 'upgrade': 1}
    build = Build('OVERGROWTH', 1, (card,), (Relic('RING_OF_THE_SNAKE'),), (), 'fixture')
    assert build.id == digest({'act_id':'OVERGROWTH', 'act':1, 'cards':[card.to_dict()],
                              'relics':[{'id':'RING_OF_THE_SNAKE','state':()}], 'ancient_history':()})
    state = {'TinkerTimeType': 2, 'TinkerTimeRider': 5}
    special = Card('MAD_SCIENCE', 1, persistent_state=state)
    changed = replace(build, cards=(special,))
    assert Build.from_dict(changed.to_dict()) == changed
    assert Card(**special.to_dict()) == special
    assert replace(changed, cards=(replace(special, persistent_state={'TinkerTimeType':2,'TinkerTimeRider':4}),)).id != changed.id


@pytest.mark.parametrize('card_id,props', [
    ('BACKFLIP', {'ints':[{'name':'Unknown','value':1}]}),
    ('MAD_SCIENCE', {'ints':[{'name':'TinkerTimeType','value':2},{'name':'TinkerTimeRider','value':9}]}),
    ('MAD_SCIENCE', {}),
    ('GUILTY', {'ints':[{'name':'CombatsSeen','value':True}]}),
    ('DOWSING', {'ints':[{'name':'RoomsEntered','value':1},{'name':'RoomsEntered','value':2}]}),
    ('SPOILS_MAP', {'ints':[{'name':'SpoilsActIndex','value':2}]}),
    ('GUILTY', {'strings': []}),
])
def test_invalid_saved_state_is_rejected(card_id, props):
    with pytest.raises(ValueError): parse_props(card_id, props)


def test_zero_defaults_and_historical_completion():
    assert normalize_state('GUILTY', {'CombatsSeen':0}) == ()
    assert normalize_state('SPOILS_MAP', {}) == ()
    assert normalize_state('DOWSING', {'RoomsEntered':5}, historical=True) == (('RoomsEntered',5),)
    with pytest.raises(ValueError):normalize_state('DOWSING', {'RoomsEntered':5})


def test_special_pools_are_inputs_but_other_characters_and_deprecated_remain_excluded(catalog):
    for card in ('SPOILS_MAP','BYRDONIS_EGG','LANTERN_KEY','DOWSING','WOUND','SHIV','SOUL'):
        assert card not in catalog.excluded['cards']
    for card in ('DEPRECATED_CARD','GENETIC_ALGORITHM','ALCHEMIZE'):
        assert card in catalog.excluded['cards']


def test_native_observation_matches_instance_state_and_requires_v3():
    a = Card('MAD_SCIENCE', persistent_state={'TinkerTimeType':2,'TinkerTimeRider':5})
    b = Card('MAD_SCIENCE', 1, persistent_state={'TinkerTimeType':3,'TinkerTimeRider':7})
    actual = [{'id': c.id, 'upgradeLevel': c.upgrade, 'persistentState': dict(c.persistent_state)} for c in (b,a)]
    validate_cards(actual, (a,b), 3)
    actual[0]['persistentState'] = dict(a.persistent_state)
    with pytest.raises(ValueError, match='differs'):validate_cards(actual, (a,b), 3)
    with pytest.raises(ValueError, match='Missing native'):validate_cards([{'id':'BACKFLIP','upgradeLevel':0}], (Card('BACKFLIP'),), 3)
    validate_cards([{'id':'BACKFLIP','upgradeLevel':0}], (Card('BACKFLIP'),), 2)


def test_joint_state_encoding_preserves_upgrade_assignment(catalog):
    encoder = Encoder.from_catalog(catalog)
    a = Card('MAD_SCIENCE', persistent_state={'TinkerTimeType':2,'TinkerTimeRider':5})
    b = Card('MAD_SCIENCE', 1, persistent_state={'TinkerTimeType':3,'TinkerTimeRider':7})
    target = catalog.acts['OVERGROWTH']['encounters'][0]['id']
    one = Build('OVERGROWTH',1,(a,b),(),(),'fixture')
    two = replace(one,cards=(replace(a,upgrade=1),replace(b,upgrade=0)))
    assert (encoder.encode(one,target,70) != encoder.encode(two,target,70)).any()


def test_dowsing_transforms_before_combat_and_not_twice(catalog):
    deck = (HistoryCard.read({'id':'CARD.DOWSING','floor_added_to_deck':1,
                             'props':state_props((('RoomsEntered',4),))}),)
    change = {'original_card':{'id':'CARD.DOWSING','floor_added_to_deck':1,
                              'props':state_props((('RoomsEntered',5),))},
              'final_card':{'id':'CARD.ABUNDANCE','floor_added_to_deck':12}}
    before, stats = enter_history_floor(deck, {'cards_transformed':[change]}, {'map_point_type':'unknown'},12,catalog)
    assert before == (HistoryCard('ABUNDANCE',0,12),)
    assert stats['cards_transformed'] == []
    assert enter_history_floor(deck, {}, {'map_point_type':'monster'},12,catalog)[0] == deck


def test_guilty_progress_does_not_include_defeat():
    deck = (HistoryCard('GUILTY',0,2),)
    node = {'rooms':[{'model_id':'ENCOUNTER.TEST'}]}
    progressed = leave_history_combat(deck,node,{'current_hp':50},last_floor=False,run={})
    assert import_card('GUILTY',0,progressed[0].extra).persistent_state == (('CombatsSeen',1),)
    assert leave_history_combat(deck,node,{'current_hp':0},last_floor=True,run={'win':False}) == deck


def test_mad_science_event_history_keeps_both_instances(catalog):
    starting = [*catalog.raw['character']['starting_deck'],'ASCENDERS_BANE']
    card = {'id':'CARD.MAD_SCIENCE','props':state_props((('TinkerTimeRider',5),('TinkerTimeType',2)))}
    node = lambda model, **changes: {'rooms':[{'model_id':model}], 'player_stats':[{'player_id':1,**changes}]}
    target = catalog.acts['OVERGROWTH']['encounters'][0]['id']
    run = {'schema_version':10,'build_id':'v0.111.0','ascension':10,'game_mode':'standard','modifiers':[],
           'acts':['ACT.OVERGROWTH'],'players':[{'id':1,'character':'CHARACTER.SILENT',
           'deck':[{'id':'CARD.'+c,'floor_added_to_deck':1} for c in starting]+[{**card,'floor_added_to_deck':2}],
           'relics':[{'id':'RELIC.RING_OF_THE_SNAKE'},{'id':'RELIC.POMANDER'}]}],
           'map_point_history':[[node('EVENT.NEOW',ancient_choice=[{'TextKey':'POMANDER','was_chosen':True}],
               relic_choices=[{'choice':'RELIC.POMANDER','was_picked':True}]),node('EVENT.TINKER_TIME',cards_gained=[card]),
               node('ENCOUNTER.'+target)]]}
    snapshots = reconstruct(run,catalog)
    assert not any(c[0]=='MAD_SCIENCE' for c in snapshots[1]['cards'])
    special = next(c for c in snapshots[2]['cards'] if c[0]=='MAD_SCIENCE')
    assert dict(import_card(*special).persistent_state) == {'TinkerTimeType':2,'TinkerTimeRider':5}
