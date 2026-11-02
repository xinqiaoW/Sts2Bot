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
from .scoring_horizon import scoring_horizon


# ArchaicTooth's saved cards only reconstruct hover tips. AfterObtained
# transforms the actual deck, which the live snapshot already contains.
# Keep this field-specific: other non-scalar saved state remains unsupported.
RELIC_DISPLAY_FIELDS = {
    'ARCHAIC_TOOTH': frozenset({'StarterCard', 'AncientCard'}),
    # The upgraded starter is already a separate relic in the owned snapshot.
    'TOUCH_OF_OROBAS': frozenset({'StarterRelic', 'UpgradedRelic'}),
}

# Verified against the live 0.111.0 game assembly, not display values. These
# saved fields accumulate forever while their effects depend on the phase.
LIVE_COUNTER_MODULI = {
    'BOOK_OF_FIVE_RINGS': ('CardsAdded', 5),
    'NUNCHAKU': ('AttacksPlayed', 10),
    'IRON_CLUB': ('CardsPlayed', 4),
    'FISHING_ROD': ('CombatsSeen', 3),
    'PAELS_WING': ('RewardsSacrificed', 2),
}
# These are equivalent for the model's single upcoming combat, not modulo
# counters: treasure count only tests >0/>1; candle only tests remaining >0;
# an already-redeemed ticket can keep counting combats after reward delivery.
LIVE_COUNTER_CAPS = {
    'SILVER_CRUCIBLE': ('TreasureRoomsEntered', 2),
    'PUMPKIN_CANDLE': ('KindleCount', 5),
    'WONGOS_MYSTERY_TICKET': ('CombatsFinished', 5),
}


def nonnegative_counter(rid, field, value):
    if type(value) is not int or not 0 <= value <= 2147483647:
        raise ValueError(f'Invalid counter value: {rid}.{field}={value!r}; expected a nonnegative Int32')
    return value


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
    if rid in LIVE_COUNTER_MODULI:
        field, period = LIVE_COUNTER_MODULI[rid]
        state[field] = nonnegative_counter(rid, field, state[field]) % period
    if rid in LIVE_COUNTER_CAPS:
        field, cap = LIVE_COUNTER_CAPS[rid]
        state[field] = min(cap, nonnegative_counter(rid, field, state[field]))
    if rid == 'LASTING_CANDY':
        field = 'CombatRewardsSeen'
        count = nonnegative_counter(rid, field, state[field])
        # Preserve zero separately from subsequent even counts.
        state[field] = 0 if count == 0 else 1 if count % 2 else 2
    if rid == 'LAVA_LAMP' and type(state['TookDamageThisCombat']) is bool:
        # Native AfterRoomEntered resets this before the modeled next combat.
        state['TookDamageThisCombat'] = False
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
    stage = payload.get('scoring_state')
    encounters = selector.catalog.acts[build['act_id']]['encounters']
    floors = []
    initial_rooms = payload['future_room_types']
    extended_short_horizon = False
    for layer, room_weights in enumerate(initial_rooms + payload.get('short_fallback_room_types', [])):
        if layer >= len(initial_rooms) and any(f['combat_probability'] > 0 for f in floors):
            break
        total = sum(room_weights.values())
        if total <= 0 or any(v < 0 for v in room_weights.values()):
            raise ValueError('Invalid reachable map probability distribution')
        targets = {}
        for room, weight in room_weights.items():
            probability = weight / total
            if room == 'Unknown':
                probability *= unknown_combat_probability
                room = 'Monster'
            if probability == 0:
                continue
            if room in ('Shop', 'Treasure', 'RestSite', 'Ancient'):
                continue
            if room == 'Boss':
                candidates = list(boss)
            elif room in ('Monster', 'Elite'):
                count = stage.get('normalCombatsCompleted') if stage else None
                weak = count < (3 if build['act'] == 1 else 2) if count is not None else None
                candidates = [e['id'] for e in encounters if e['room_type'] == room
                              and (room != 'Monster' or weak is None or e['weak'] == weak)]
            else:
                raise ValueError('Unsupported map node: ' + room)
            if not candidates:
                raise ValueError('No encounters for reachable room: ' + room)
            for target in candidates:
                targets[target] = targets.get(target, 0) + probability / len(candidates)
        floor = dict(targets=targets, combat_probability=min(1.0, sum(targets.values())))
        if layer < len(initial_rooms):
            floors.append(floor)
        elif targets:
            floors = [floor]
            extended_short_horizon = True
            break
    # Older snapshots retain their explicitly supplied Boss until the updated
    # native capture provides completed combat counts and act-end evidence.
    horizon = None
    request = dict(build=build, max_hp=payload['max_hp'], options=options,
                   floors_to_boss=payload['floors_to_boss'], next_floors=floors, boss_targets=boss)
    if stage is not None:
        horizon = scoring_horizon(selector.catalog, selector.scorer.predictor.trained_targets,
            dict(stage, act=build['act'], actId=build['act_id']),
            elite_loss_threshold=selector.config['elite_target_loss_threshold'],
            boss_after_act_floor=selector.config['boss_target_after_act_floor'],
            score_elites=lambda act_id, targets: selector.scorer.score_many([
                dict(build=build, max_hp=payload['max_hp'], targets=targets, encounter_act_id=act_id)],
                strict=selector.config['strict_features'])[0])
        short_targets = horizon['short_targets']
        if short_targets is not None:
            request['next_floors'] = [dict(targets=short_targets, combat_probability=1.0)] if short_targets else []
        request.update(long_targets=horizon['long_targets'], long_target_room=horizon['long_target_room'],
                       long_target_aggregation=horizon.get('long_target_aggregation', 'mean'),
                       encounter_act_id=horizon['encounter_act_id'], terminal=horizon['mode'] == 'terminal')
        if horizon['projects_next_act']:
            request['rollout_depth'] = selector.config['post_boss_rollout_depth']
    result = selector.select(request)
    baseline = result['candidates'][-1]['combined_score']
    for row in result['candidates']:
        row.pop('leaves')  # UI only needs compact immutable numeric results.
        row['delta'] = row['combined_score'] - baseline
    result['protocol'] = 1
    result['request_id'] = payload['request_id']
    result['normalized_relics'] = ignored
    result['extended_short_horizon'] = extended_short_horizon
    result['scoring_horizon'] = horizon
    if horizon:
        result['warnings'] = sorted(set(result['warnings'] + horizon['warnings']))
    result['scenario_note'] = '满血构筑评分；地图分支等概率，同类敌人等概率；未知房战斗概率 ' + str(unknown_combat_probability)
    if horizon:
        result['scenario_note'] += {'elite_risk': '；精英预计掉血超过阈值：长期目标为本幕精英',
            'boss': '；长期目标：本幕待战 Boss',
            'next_act_elite_risk': '；本幕已通关：短期看下一幕弱普通怪，精英预计掉血较高，长期看下一幕精英',
            'next_act_boss': '；本幕已通关：短期看下一幕弱普通怪，长期看下一幕公开 Boss 池',
            'terminal': '；已通关，无未来战斗，选牌收益为零'}[horizon['mode']]
        if horizon.get('long_target_aggregation') == 'max':
            result['scenario_note'] += '；双 Boss 分别预测，长期取掉血较多者'
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
