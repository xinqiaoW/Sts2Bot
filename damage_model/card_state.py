"""Explicit saved card fields from native 0.111.0; unknown state is never guessed."""
from dataclasses import replace
import json

SPECIAL_POOLS = ('QUEST_CARD_POOL', 'STATUS_CARD_POOL', 'TOKEN_CARD_POOL')
QUEST_CARDS = {'BYRDONIS_EGG', 'DOWSING', 'LANTERN_KEY', 'SPOILS_MAP'}
# Defaults are native instance defaults, including SpoilsMap.AfterCreated.
DEFAULTS = {'DOWSING': {'RoomsEntered': 0}, 'GUILTY': {'CombatsSeen': 0},
            'SPOILS_MAP': {'SpoilsActIndex': 1},
            'MAD_SCIENCE': {'TinkerTimeType': 0, 'TinkerTimeRider': 0}}


def normalize_state(card_id, state, *, historical=False):
    if not isinstance(state, dict) or any(type(k) is not str or type(v) is not int for k, v in state.items()):
        raise ValueError('Invalid persistent card state fields')
    defaults = DEFAULTS.get(card_id, {})
    if set(state) - set(defaults):
        raise ValueError('Unsupported persistent card state: ' + card_id)
    values = {**defaults, **state}
    for key in ('RoomsEntered', 'CombatsSeen'):
        if key in values and not 0 <= values[key] <= (5 if historical else 4):
            raise ValueError('Invalid quest/curse progress')
    if card_id == 'SPOILS_MAP' and values['SpoilsActIndex'] != 1:
        raise ValueError('Invalid Spoils Map act')
    if card_id == 'MAD_SCIENCE':
        kind, rider = values['TinkerTimeType'], values['TinkerTimeRider']
        if kind not in (1, 2, 3) or rider not in range(3 * kind - 2, 3 * kind + 1):
            raise ValueError('Invalid Mad Science type/rider combination')
    return tuple(sorted((k, v) for k, v in values.items() if v != defaults[k]))


def parse_props(card_id, props, *, historical=False):
    if props is None:
        return normalize_state(card_id, {}, historical=historical)
    if not isinstance(props, dict) or set(props) - {'ints'} or not isinstance(props.get('ints', []), list):
        raise ValueError('Unsupported persistent card state: props')
    values = {}
    for item in props.get('ints', []):
        if not isinstance(item, dict) or set(item) != {'name', 'value'} or type(item['name']) is not str or item['name'] in values:
            raise ValueError('Invalid or duplicate saved card property')
        values[item['name']] = item['value']
    return normalize_state(card_id, values, historical=historical)


def state_props(state):
    return {'ints': [{'name': k, 'value': v} for k, v in state]}


def normalize_extra(card_id, extra, *, historical=False):
    values = dict(extra)
    if card_id not in DEFAULTS:
        return values  # Preserve unsupported fields for per-snapshot rejection.
    state = parse_props(card_id, values.pop('props', None), historical=historical)
    if state:
        values['props'] = state_props(state)
    return values


def state_variants(card_id):
    if card_id == 'MAD_SCIENCE':
        return [normalize_state(card_id, {'TinkerTimeType': t, 'TinkerTimeRider': r})
                for t in (1, 2, 3) for r in range(3*t-2, 3*t+1)]
    if card_id in ('DOWSING', 'GUILTY'):
        key = next(iter(DEFAULTS[card_id]))
        return [normalize_state(card_id, {key: v}) for v in range(5)]
    return [()]


def history_progress(card, key, increment=1):
    extra = json.loads(card.extra)
    state = dict(parse_props(card.id, extra.get('props'), historical=True))
    state[key] = state.get(key, DEFAULTS[card.id][key]) + increment
    normalized = normalize_state(card.id, state, historical=True)
    extra.pop('props', None)
    if normalized:
        extra['props'] = state_props(normalized)
    from .schema import canonical
    return replace(card, extra=canonical(extra))


def state_description(card_id, state):
    values = {**DEFAULTS.get(card_id, {}), **dict(state)}
    if card_id == 'MAD_SCIENCE':
        types = {1: '攻击', 2: '技能', 3: '能力'}
        riders = {1: '虚弱＋易伤', 2: '三连击', 3: '窒息', 4: '获得能量', 5: '抽牌',
                  6: '生成卡牌', 7: '力量＋敏捷', 8: '好奇', 9: '改进'}
        return types[values['TinkerTimeType']] + '／' + riders[values['TinkerTimeRider']]
    if card_id == 'DOWSING': return '问号房进度 ' + str(values['RoomsEntered']) + '/5'
    if card_id == 'GUILTY': return '战斗进度 ' + str(values['CombatsSeen']) + '/5'
    if card_id == 'SPOILS_MAP': return '宝藏：第二幕'
    return ''
