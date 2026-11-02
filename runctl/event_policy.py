"""Event decisions from displayed option text and public event rules.

No event model, generated reward or future random outcome is available here.
Unknown option text is logged as a heuristic instead of claiming model parity.
"""
import re


def forbidden_event_reward(option):
    """Explicit user ban: Storybook grants Brightest Flame on acquisition."""
    return ((option.get('relic') or {}).get('id') == 'STORYBOOK'
            or option.get('id', '').upper().split('.')[-1] == 'STORYBOOK')


def doll_room_options(options):
    """User rule: reveal two dolls, then never take Bing Bong.

    Native DollRoom options can have relic=None and a localized TextKey.
    Match explicit public identities, never their position or hidden rewards.
    """
    def key(option):
        return option.get('id', '').upper().split('.')[-1]

    initial = {'RANDOM', 'TAKE_SOME_TIME', 'EXAMINE'}
    if any(key(o) in initial for o in options):
        allowed = [o for o in options if key(o) == 'TAKE_SOME_TIME' and not o.get('lethal')]
        if len(allowed) != 1:
            raise ValueError('DOLL_ROOM: required TAKE_SOME_TIME option is unavailable or lethal; refusing random doll')
        return allowed, 'doll_room_take_some_time'

    def identity(option):
        relic_id = (option.get('relic') or {}).get('id')
        if relic_id:
            return relic_id
        aliases = {'宾邦': 'BING_BONG', '冰邦': 'BING_BONG', 'Bing Bong': 'BING_BONG',
                   '风的女儿': 'DAUGHTER_OF_THE_WIND', 'Daughter of the Wind': 'DAUGHTER_OF_THE_WIND',
                   '抱抱先生': 'MR_STRUGGLES', 'Mr. Struggles': 'MR_STRUGGLES'}
        for value in (option.get('id', ''), option.get('title', '')):
            value = re.sub(r'\[[^\]]+\]|<[^>]+>', '', value).strip()
            if value in aliases:
                return aliases[value]
            if value in ('BING_BONG', 'DAUGHTER_OF_THE_WIND', 'MR_STRUGGLES'):
                return value
        return None

    allowed = [o for o in options if not o.get('lethal') and identity(o) != 'BING_BONG'
               and (identity(o) in ('DAUGHTER_OF_THE_WIND', 'MR_STRUGGLES') or o.get('proceed'))]
    if not allowed:
        raise ValueError('DOLL_ROOM: no recognized safe option; BING_BONG is forbidden')
    return allowed, 'doll_room_exclude_bing_bong'


def event_value(event_id, option, state, config):
    if option.get('lethal'):
        return -1e9, 'visible_lethal_option'
    key = option.get('id', '').upper().split('.')[-1]
    text = re.sub(r'\[[^\]]+\]|<[^>]+>', '', option.get('description', '')).lower()
    missing = state['maxHp'] - state['hp']
    hp_weight = 1 + 2*(1-state['hp']/state['maxHp'])
    value = 0.0
    recognized = False
    # Maximum HP is a persistent resource, not ordinary heal/damage. In
    # particular Tablet of Truth's escalating max-HP costs must not disappear
    # just because its text also promises an upgrade.
    maximum_pattern = r'(gain|obtain|lose|pay|获得|失去|增加|减少)\s*(\d+)\s*(?:点\s*)?(?:max(?:imum)?\s+(?:hp|health)|最大生命(?:值)?)'
    for match in re.finditer(maximum_pattern, text):
        recognized = True
        amount = int(match[2])
        negative = match[1] in ('lose', 'pay', '失去', '减少')
        value += amount * config['event_max_hp_value'] * (-1 if negative else 1)
        if negative:
            value -= hp_weight * max(0, state['hp']-(state['maxHp']-amount))
    text = re.sub(maximum_pattern, '', text)
    for pattern, sign in [(r'(?:heal|recover|恢复|回复)\s*(\d+)', 1),
                          (r'(?:lose|take|失去|受到)\s*(\d+)\s*(?:hp|health|damage|点?生命|点?伤害)', -1)]:
        for match in re.finditer(pattern, text):
            amount = int(match[1]); recognized = True
            value += hp_weight * (min(missing, amount) if sign > 0 else -amount)
    for match in re.finditer(r'(gain|obtain|lose|pay|获得|失去|支付)\s*(\d+)\s*(?:gold|金币)', text):
        recognized = True
        value += int(match[2]) * config['gold_hp_value'] * (-1 if match[1] in ('lose', 'pay', '失去', '支付') else 1)
    for words, benefit in [(['upgrade', '升级'], config['event_upgrade_value']),
                           (['remove', '移除'], config['event_remove_value']),
                           (['enchant', '附魔'], config['event_enchant_value']),
                           (['relic', '遗物'], config['event_relic_value']),
                           (['curse', '诅咒'], -config['event_curse_cost']),
                           (['transform', '变化'], config['event_transform_value']),
                           (['choose a card', '选择一张牌'], config['event_card_value'])]:
        if any(word in text for word in words): value += benefit; recognized = True
    # These rules use static, public event mechanics, never the future result.
    if event_id == 'WELLSPRING':
        if key == 'BOTTLE':
            return (config['potion_value'] if any(p['id'] is None for p in state.get('potions', [])) else 0), 'wellspring_unknown_potion_prior'
        if key == 'BATHE':
            return config['event_remove_value']-config['event_curse_cost'], 'wellspring_remove_and_guilty_cost'
    if event_id == 'TABLET_OF_TRUTH' and key.startswith('DECIPHER'):
        return value, 'tablet_displayed_escalating_max_hp_cost'
    if event_id == 'DENSE_VEGETATION' and key == 'REST':
        # The public event rule guarantees an ensuing fight. Its generated
        # combat state is not read here; use an explicit conservative prior.
        return value - config['event_fight_cost'], 'dense_vegetation_rest_then_fight_prior'
    if event_id == 'UNREST_SITE' and key == 'REST' and not any(w in text for w in ('curse', '诅咒')):
        return value-config['event_curse_cost'], 'unrest_heal_and_poor_sleep_cost'
    if event_id == 'BRAIN_LEECH' and key == 'SHARE_KNOWLEDGE':
        return value, 'brain_leech_forced_choice_of_five'
    if event_id == 'SLIPPERY_BRIDGE':
        # The model policy compares the exact owned card against short/long
        # targets. Reroll costs only its displayed HP, without an extra -10.
        return (0 if key == 'OVERCOME' else value), 'slippery_bridge_displayed_hp_cost'
    if event_id == 'COLOSSAL_FLOWER':
        if 'EXTRACT_CURRENT_PRIZE' in key: return value + 4, 'colossal_flower_cash_out'
        if 'REACH_DEEPER' in key:
            return value + (8 if state['hp'] > .8*state['maxHp'] else -10), 'colossal_flower_hp_budget'
    if event_id == 'SELF_HELP_BOOK' and key == 'READ_ENTIRE_BOOK':
        return value + 4, 'self_help_book_multi_enchantment'
    if option.get('proceed') or any(word in key for word in ('LEAVE', 'IGNORE', 'REFUSE', 'NO_OPTIONS')):
        return 0, 'leave_event'
    return value, 'visible_text_heuristic' if recognized else 'unknown_event_option_neutral'


def event_health_delta(option, state):
    """Only displayed immediate healing/damage; no future reward assumptions."""
    text = re.sub(r'\[[^\]]+\]|<[^>]+>', '', option.get('description', '')).lower()
    # Maximum-HP effects need their own semantics, not ordinary damage parsing.
    text = re.sub(r'(?:gain|obtain|lose|pay|获得|失去|增加|减少)\s*\d+\s*(?:点\s*)?(?:max(?:imum)?\s+(?:hp|health)|最大生命(?:值)?)', '', text)
    heal = sum(int(m[1]) for m in re.finditer(r'(?:heal|recover|恢复|回复)\s*(\d+)', text))
    loss = sum(int(m[1]) for m in re.finditer(r'(?:lose|take|失去|受到)\s*(\d+)\s*(?:点\s*)?(?:hp|health|damage|生命|伤害)', text))
    return min(state['maxHp']-state['hp'], heal) - loss


def event_card_addition(event_id, option):
    """Public forced additions only. Hover tips alone do not imply acquisition.

    Multiplicity is a public rule: Enlightenment has one hover tip but adds
    two copies. Generated grid offers remain unknown until that page opens.
    """
    key = option.get('id', '').upper().split('.')[-1]
    rules = {
        ('SPIRIT_GRAFTER', 'LET_IT_IN'): (1, 'METAMORPHOSIS'),
        ('ZEN_WEAVER', 'BREATHING_TECHNIQUES'): (2, 'ENLIGHTENMENT'),
        ('ROOM_FULL_OF_CHEESE', 'GORGE'): (2, None),
        ('BRAIN_LEECH', 'SHARE_KNOWLEDGE'): (1, None),
        ('BUGSLAYER', 'EXTERMINATION'): (1, 'EXTERMINATE'),
        ('BUGSLAYER', 'SQUASH'): (1, 'SQUASH'),
        ('BYRDONIS_NEST', 'TAKE'): (1, None),
        ('ENDLESS_CONVEYOR', 'FRIED_EEL'): (1, None),
        ('ENDLESS_CONVEYOR', 'SEAPUNK_SALAD'): (1, None),
        ('TINKER_TIME', 'CHOOSE_CARD_TYPE'): (1, None),
    }
    rule = rules.get((event_id, key))
    if rule is None:
        return None
    count, card_id = rule
    previews = [p['card'] for p in option.get('cards', []) if p.get('deckIndex', -1) < 0
                and (card_id is None or p['card']['id'] == card_id)]
    # Random/custom card events must not treat incidental hover tips as their
    # actual future outcome. Only the egg and salad explicitly show the card.
    if card_id is None and (event_id, key) not in {('BYRDONIS_NEST', 'TAKE'), ('ENDLESS_CONVEYOR', 'SEAPUNK_SALAD')}:
        return dict(count=count, cards=None)
    card = previews[0] if len(previews) == 1 else dict(id=card_id) if card_id else None
    return dict(count=count, cards=[dict(card) for _ in range(count)] if card else None)
