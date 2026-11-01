"""Event decisions from displayed option text and public event rules.

No event model, generated reward or future random outcome is available here.
Unknown option text is logged as a heuristic instead of claiming model parity.
"""
import re


def event_value(event_id, option, state, config):
    if option.get('lethal'):
        return -1e9, 'visible_lethal_option'
    key = option.get('id', '').upper().split('.')[-1]
    text = re.sub(r'\[[^\]]+\]|<[^>]+>', '', option.get('description', '')).lower()
    missing = state['maxHp'] - state['hp']
    hp_weight = 1 + 2*(1-state['hp']/state['maxHp'])
    value = 0.0
    recognized = False
    for pattern, sign in [(r'(?:heal|recover|恢复|回复)\s*(\d+)', 1),
                          (r'(?:lose|take|失去|受到)\s*(\d+)\s*(?:hp|health|damage|点?生命|点?伤害)', -1)]:
        for match in re.finditer(pattern, text):
            amount = int(match[1]); recognized = True
            value += hp_weight * (min(missing, amount) if sign > 0 else -amount)
    for match in re.finditer(r'(gain|obtain|lose|pay|获得|失去|支付)\s*(\d+)\s*(?:gold|金币)', text):
        recognized = True
        value += int(match[2]) * config['gold_hp_value'] * (-1 if match[1] in ('lose', 'pay', '失去', '支付') else 1)
    for words, benefit in [(['upgrade', '升级'], 5), (['remove', '移除'], 5),
                           (['enchant', '附魔'], 5), (['relic', '遗物'], 8),
                           (['curse', '诅咒'], -8), (['transform', '变化'], 3),
                           (['choose a card', '选择一张牌'], 3)]:
        if any(word in text for word in words): value += benefit; recognized = True
    # These rules use static, public event mechanics, never the future result.
    if event_id == 'BRAIN_LEECH' and key == 'SHARE_KNOWLEDGE':
        return value + 5, 'brain_leech_free_choice_of_five'
    if event_id == 'SLIPPERY_BRIDGE':
        # Repeated holds consume increasingly more HP. The currently offered
        # removal is visible; until card hover-tip identities are exported,
        # take the deterministic removal instead of cycling blind guesses.
        return (5 if key == 'OVERCOME' else value - 10), 'slippery_bridge_avoid_repeated_hp_loss'
    if event_id == 'COLOSSAL_FLOWER':
        if 'EXTRACT_CURRENT_PRIZE' in key: return value + 4, 'colossal_flower_cash_out'
        if 'REACH_DEEPER' in key:
            return value + (8 if state['hp'] > .8*state['maxHp'] else -10), 'colossal_flower_hp_budget'
    if event_id == 'SELF_HELP_BOOK' and key == 'READ_ENTIRE_BOOK':
        return value + 4, 'self_help_book_multi_enchantment'
    if option.get('proceed') or any(word in key for word in ('LEAVE', 'IGNORE', 'REFUSE', 'NO_OPTIONS')):
        return 0, 'leave_event'
    return value, 'visible_text_heuristic' if recognized else 'unknown_event_option_neutral'
