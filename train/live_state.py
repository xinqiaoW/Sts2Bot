"""Normalize public native card/relic state for both Bot and HTTP scoring."""
from damage_model.card_state import normalize_state
from damage_model.catalog import COUNTER_DOMAINS

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


