"""Local HTTP bridge for CombatSolver's out-of-combat card advisor."""
from __future__ import annotations

import argparse
from http.server import BaseHTTPRequestHandler, HTTPServer
import json

from damage_model.card_state import normalize_state
from damage_model.catalog import COUNTER_DOMAINS
from damage_model.schema import Build
from .reward_policy import RewardSelector, load_config
from .score import BuildScorer, DEFAULT_CHECKPOINT


# ArchaicTooth's saved cards only reconstruct hover tips. AfterObtained
# transforms the actual deck, which the live snapshot already contains.
# Keep this field-specific: other non-scalar saved state remains unsupported.
RELIC_DISPLAY_FIELDS = {'ARCHAIC_TOOTH': frozenset({'StarterCard', 'AncientCard'})}


def normalize_card(card):
    card = dict(card)
    if card.pop('unsupported_fields', []):
        raise ValueError('Card has unsupported saved fields: ' + card['id'])
    card['persistent_state'] = dict(normalize_state(card['id'], card.get('persistent_state', {})))
    return card


def normalize_relic(original):
    relic = dict(original)
    rid = relic['id']
    unsupported = set(relic.pop('unsupported_fields', [])) - RELIC_DISPLAY_FIELDS.get(rid, frozenset())
    if unsupported:
        raise ValueError(f'Unsupported relic saved fields: {rid}; {sorted(unsupported)}')
    state = {}
    for key, value in relic['state']:
        if key in state:
            raise ValueError(f'Invalid relic state: {rid}; duplicate field {key}')
        state[key] = value
    # Native RelicModel declares these inherited SavedProperty booleans on
    # every relic. The training schema represents ordinary, unmelted relics;
    # only explicit false is equivalent to that schema (not 0 or "false").
    for key in ('IsWax', 'IsMelted'):
        if key in state:
            if state[key] is not False:
                raise ValueError(f'Unsupported relic state: {rid}; {key}={state[key]!r} '
                                 '(模型仅支持非蜡制、未融化的遗物)')
            del state[key]
    expected = set(COUNTER_DOMAINS.get(rid, {}))
    if set(state) != expected:
        raise ValueError(f'Incomplete relic state: {rid}; '
                         f'missing={sorted(expected - state.keys())}; '
                         f'unexpected={sorted(state.keys() - expected)}')
    # Native BookOfFiveRings keeps a cumulative Int32 CardsAdded; both its
    # display and healing trigger use CardsAdded % 5. Training stores only
    # that equivalent phase, not the lifetime total. Do not mutate live state
    # or replay the heal (this scorer starts each simulated fight at full HP).
    if rid == 'BOOK_OF_FIVE_RINGS':
        count = state['CardsAdded']
        if type(count) is not int or not 0 <= count <= 2147483647:
            raise ValueError(f'Invalid counter value: {rid}.CardsAdded={count!r}; '
                             'expected a nonnegative Int32')
        state['CardsAdded'] = count % 5
    for key, value in state.items():
        domain = COUNTER_DOMAINS[rid][key]
        if not any(type(value) is type(allowed) and value == allowed for allowed in domain):
            raise ValueError(f'Invalid counter value: {rid}.{key}={value!r}; expected {domain}')
    relic['state'] = [[key, value] for key, value in sorted(state.items())]
    return relic


def evaluate(payload, selector, unknown_combat_probability=0.25):
    if payload.get('protocol') != 1:
        raise ValueError('Unsupported advisor protocol')
    if payload.get('character') != 'SILENT' or payload.get('ascension') != 10:
        raise ValueError('模型仅支持静默猎手 A10')
    build = dict(payload['build'])
    build['cards'] = [normalize_card(c) for c in build['cards']]
    # Same explicit normalization used by the training collector. Report losses
    # of scope rather than silently claiming to represent these relic effects.
    ignored = []
    relics = []
    for original in build['relics']:
        relic = dict(original)
        if relic['id'] in selector.catalog.normalized_relic_ids:
            ignored.append(relic['id'])
            continue
        relics.append(normalize_relic(relic))
    build['relics'] = relics
    selector.catalog.validate(Build.from_dict(build))
    options = []
    for row in payload['options']:
        option = {k: row[k] for k in ('action', 'deck_index') if k in row}
        if 'card' in row:
            option['card'] = normalize_card(row['card'])
        options.append(option)
    boss = payload['boss_targets']
    encounters = selector.catalog.acts[build['act_id']]['encounters']
    floors = []
    for room_weights in payload['future_room_types']:
        total = sum(room_weights.values())
        if total <= 0 or any(v < 0 for v in room_weights.values()):
            raise ValueError('Invalid reachable map probability distribution')
        targets = {}
        for room, weight in room_weights.items():
            probability = weight / total
            if room == 'Unknown':
                probability *= unknown_combat_probability
                room = 'Monster'
            if room in ('Shop', 'Treasure', 'RestSite', 'Ancient'):
                continue
            if room == 'Boss':
                candidates = list(boss)
            elif room in ('Monster', 'Elite'):
                candidates = [e['id'] for e in encounters if e['room_type'] == room]
            else:
                raise ValueError('Unsupported map node: ' + room)
            if not candidates:
                raise ValueError('No encounters for reachable room: ' + room)
            for target in candidates:
                targets[target] = targets.get(target, 0) + probability / len(candidates)
        floors.append(dict(targets=targets, combat_probability=min(1.0, sum(targets.values()))))
    request = dict(build=build, max_hp=payload['max_hp'], options=options,
                   floors_to_boss=payload['floors_to_boss'], next_floors=floors, boss_targets=boss)
    result = selector.select(request)
    baseline = result['candidates'][-1]['combined_score']
    for row in result['candidates']:
        row.pop('leaves')  # UI only needs compact immutable numeric results.
        row['delta'] = row['combined_score'] - baseline
    result['protocol'] = 1
    result['request_id'] = payload['request_id']
    result['normalized_relics'] = ignored
    result['scenario_note'] = '满血构筑评分；地图分支等概率，同类敌人等概率；未知房战斗概率 ' + str(unknown_combat_probability)
    return result


def make_handler(selector, unknown_combat_probability):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.reply(200 if self.path == '/health' else 404,
                       dict(protocol=1, model=selector.scorer.predictor.name))

        def do_POST(self):
            if self.path != '/score':
                self.reply(404, dict(error='Unknown endpoint')); return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 2_000_000:
                    raise ValueError('Request size must be 1..2000000 bytes')
                payload = json.loads(self.rfile.read(length))
                result = evaluate(payload, selector, unknown_combat_probability)
            except (ValueError, KeyError, TypeError) as exc:
                self.reply(422, dict(error=str(exc))); return
            self.reply(200, result)

        def reply(self, status, body):
            data = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            try:
                self.wfile.write(data)
            except (BrokenPipeError, ConnectionResetError):
                pass  # Caller closed the selection screen during inference.

    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', default=str(DEFAULT_CHECKPOINT))
    parser.add_argument('--config', default=None)
    parser.add_argument('--port', type=int, default=18765)
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--unknown-combat-probability', type=float, default=0.25)
    args = parser.parse_args()
    if not 0 <= args.unknown_combat_probability <= 1:
        parser.error('unknown combat probability must be between 0 and 1')
    config = load_config(args.config)
    import torch
    torch.set_num_threads(config['cpu_threads'])
    selector = RewardSelector(BuildScorer(args.checkpoint, args.device), config)
    # Single worker bounds model memory and serializes requests from the mod.
    server = HTTPServer(('127.0.0.1', args.port), make_handler(selector, args.unknown_combat_probability))
    server.timeout = 120
    print(f'CombatSolver advisor ready at http://127.0.0.1:{args.port}', flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
