import json
from urllib.request import Request, build_opener, ProxyHandler
from http.server import HTTPServer
from threading import Thread

import pytest

from test_reward_policy import request_data, selector
from train.advisor_service import evaluate, make_handler


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
