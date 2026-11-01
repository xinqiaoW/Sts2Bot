import json
from copy import deepcopy
from urllib.request import Request, build_opener, ProxyHandler
from http.server import HTTPServer
from threading import Thread

import pytest

from test_reward_policy import request_data, selector
from train.advisor_service import evaluate, make_handler, normalize_relic


@pytest.mark.parametrize('count,phase', [(0, 0), (4, 4), (5, 0), (6, 1),
                                       (9, 4), (10, 0), (2147483647, 2)])
def test_book_of_five_rings_cumulative_counter(count, phase):
    native = dict(id='BOOK_OF_FIVE_RINGS',
                  state=[['CardsAdded', count], ['IsWax', False], ['IsMelted', False]])
    original = deepcopy(native)
    assert normalize_relic(native) == dict(id='BOOK_OF_FIVE_RINGS', state=[['CardsAdded', phase]])
    assert native == original


@pytest.mark.parametrize('count', [-1, True, 5.0, '5', 2147483648])
def test_book_of_five_rings_rejects_invalid_native_counter(count):
    with pytest.raises(ValueError, match='BOOK_OF_FIVE_RINGS.*CardsAdded'):
        normalize_relic(dict(id='BOOK_OF_FIVE_RINGS', state=[['CardsAdded', count]]))


def test_invalid_counter_error_identifies_other_relic():
    with pytest.raises(ValueError, match='PEN_NIB.*AttacksPlayed.*10'):
        normalize_relic(dict(id='PEN_NIB', state=[['AttacksPlayed', 10]]))


def test_archaic_tooth_tooltips_match_training_state():
    native = dict(id='ARCHAIC_TOOTH', state=[['IsWax', False], ['IsMelted', False]],
                  unsupported_fields=['StarterCard', 'AncientCard'])
    original = deepcopy(native)
    assert normalize_relic(native) == dict(id='ARCHAIC_TOOTH', state=[])
    assert native == original


def test_orobas_starter_tooltips_do_not_duplicate_owned_relic_effect():
    native = dict(id='TOUCH_OF_OROBAS', state=[], unsupported_fields=['StarterRelic', 'UpgradedRelic'])
    assert normalize_relic(native) == dict(id='TOUCH_OF_OROBAS', state=[])
    with pytest.raises(ValueError, match='UnknownRelic'):
        normalize_relic(dict(native, unsupported_fields=['StarterRelic', 'UnknownRelic']))


@pytest.mark.parametrize('rid,fields,invalid', [
    ('ARCHAIC_TOOTH', ['StarterCard', 'AncientCard', 'UnknownCard'], 'UnknownCard'),
    ('PEN_NIB', ['StarterCard'], 'StarterCard'),
])
def test_tooth_adapter_does_not_allow_unknown_saved_fields(rid, fields, invalid):
    with pytest.raises(ValueError, match=rid + '.*' + invalid):
        normalize_relic(dict(id=rid, state=[], unsupported_fields=fields))


def test_archaic_tooth_still_rejects_wax_state():
    with pytest.raises(ValueError, match='ARCHAIC_TOOTH.*IsWax'):
        normalize_relic(dict(id='ARCHAIC_TOOTH', state=[['IsWax', True]],
                             unsupported_fields=['StarterCard', 'AncientCard']))


def test_native_relic_base_flags_match_training_input(request_data):
    s = selector()
    s.catalog.acts['OVERGROWTH']['encounters'] = [dict(id='FLYCONID_NORMAL', room_type='Monster')]
    p = payload(request_data)
    p['build']['relics'] = [dict(id='RING_OF_THE_SNAKE', state=[]),
                           dict(id='PRECISE_SCISSORS', state=[]),
                           dict(id='PEN_NIB', state=[['AttacksPlayed', 7]])]
    p['build']['ancient_history'] = [[1, 'NEOW', 'PRECISE_SCISSORS']]
    expected = evaluate(p, s)
    for relic in p['build']['relics']:
        relic['state'].extend([['IsWax', False], ['IsMelted', False]])
    original = deepcopy(p)
    actual = evaluate(p, s)
    actual.pop('elapsed_seconds')
    expected.pop('elapsed_seconds')
    assert actual == expected
    assert p == original


@pytest.mark.parametrize('flag,value', [('IsWax', True), ('IsMelted', True),
                                      ('IsWax', 0), ('IsMelted', 'false')])
def test_reject_active_or_malformed_relic_flags(request_data, flag, value):
    p = payload(request_data)
    p['build']['relics'][0]['state'] = [[flag, value]]
    with pytest.raises(ValueError, match='RING_OF_THE_SNAKE.*' + flag):
        evaluate(p, selector())


@pytest.mark.parametrize('state,detail', [([], 'missing=.*AttacksPlayed'),
    ([['AttacksPlayed', 2], ['UnknownCounter', 0]], 'unexpected=.*UnknownCounter'),
    ([['AttacksPlayed', 2], ['AttacksPlayed', 3]], 'duplicate.*AttacksPlayed')])
def test_relic_state_errors_identify_relic_and_field(request_data, state, detail):
    p = payload(request_data)
    p['build']['relics'] = [*p['build']['relics'], dict(id='PEN_NIB', state=state)]
    with pytest.raises(ValueError, match='PEN_NIB.*' + detail):
        evaluate(p, selector())


def payload(request_data):
    return dict(protocol=1, request_id='scene-42', character='SILENT', ascension=10,
                build=request_data['build'], max_hp=70, floors_to_boss=1,
                options=[dict(action='take', card=c) for c in request_data['rewards']],
                future_room_types=[{'Monster': 1}, {'RestSite': 1}],
                boss_targets=request_data['boss_targets'])


def test_live_bridge_normalization_and_baseline(request_data):
    s = selector()
    # Service expands room categories to catalog enemies: use only its known
    # catalog encounters and verify the resulting mean independently.
    s.catalog.acts['OVERGROWTH']['encounters'] = [dict(id='FLYCONID_NORMAL', room_type='Monster')]
    p = payload(request_data)
    r = evaluate(p, s)
    assert r['request_id'] == 'scene-42'
    assert len(r['candidates']) == 4
    assert r['candidates'][-1]['delta'] == 0
    assert r['candidates'][-1]['short_expected_hp_loss'] == pytest.approx(10/1.8)
    assert all('leaves' not in c for c in r['candidates'])
    p['future_room_types'] = [{'Unknown': 1}]
    assert evaluate(p, s, 0.25)['candidates'][-1]['short_expected_hp_loss'] == 2.5


def test_reject_other_character_unknown_state_and_room(request_data):
    s = selector(); p = payload(request_data)
    p['character'] = 'IRONCLAD'
    with pytest.raises(ValueError, match='A10'): evaluate(p, s)
    p['character'] = 'SILENT'
    p['build']['cards'][0]['unsupported_fields'] = ['model_ids']
    with pytest.raises(ValueError, match='saved fields'): evaluate(p, s)
    p['build']['cards'][0].pop('unsupported_fields')
    p['future_room_types'] = [{'Unassigned': 1}]
    with pytest.raises(ValueError, match='Unsupported map'): evaluate(p, s)


def test_http_protocol_and_error_responses(request_data):
    s = selector()
    s.scorer.predictor.name = 'test-model'
    s.catalog.acts['OVERGROWTH']['encounters'] = [dict(id='FLYCONID_NORMAL', room_type='Monster')]
    server = HTTPServer(('127.0.0.1', 0), make_handler(s, 0.25))
    thread = Thread(target=server.serve_forever, daemon=True); thread.start()
    try:
        url = f'http://127.0.0.1:{server.server_port}'
        opener = build_opener(ProxyHandler({}))
        with opener.open(url+'/health') as response:
            assert json.load(response)['protocol'] == 1
        request = Request(url+'/score', json.dumps(payload(request_data)).encode(), {'Content-Type': 'application/json'})
        with opener.open(request) as response:
            assert json.load(response)['request_id'] == 'scene-42'
    finally:
        server.shutdown(); thread.join(); server.server_close()
