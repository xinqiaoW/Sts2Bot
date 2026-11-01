import pytest

from runctl.policy_config import choose_card_with_margin, load_policy_config
from test_reward_policy import request_data, FakeScorer
from runctl.policy import BotPolicy
from runctl.route_policy import plan_route, next_floors
from runctl.batch import summarize
from runctl.event_policy import event_value


@pytest.mark.parametrize('gain,expected', [(-1, 3), (0, 3), (0.99, 3), (1, 3), (1.0001, 0), (2, 0)])
def test_normal_card_requires_strictly_more_than_one(gain, expected):
    assert choose_card_with_margin({0: -20+gain, 1: -30, 3: -20}, 3,
                                   crisis=False, config=load_policy_config()) == expected


def test_crisis_and_forced_choices():
    config = load_policy_config()
    assert choose_card_with_margin({0: -19.9, 3: -20}, 3, crisis=True, config=config) == 0
    assert choose_card_with_margin({0: -20, 3: -20}, 3, crisis=True, config=config) == 3
    assert choose_card_with_margin({0: -30, 2: -40}, None, crisis=False, config=config) == 0


def test_configured_threshold_and_weights():
    config = load_policy_config(normal_card_min_gain=2)
    assert config['short_weight'] == .35 and config['long_weight'] == .65
    assert choose_card_with_margin({0: 2, 1: 0}, 1, crisis=False, config=config) == 1
    assert choose_card_with_margin({0: 2.01, 1: 0}, 1, crisis=False, config=config) == 0


@pytest.mark.parametrize('overrides', [{'normal_card_min_gain': -1}, {'short_weight': 0, 'long_weight': 0},
    {'crisis_samples_per_parent': 1, 'crisis_keep_per_parent': 4}, {'max_rollout_depth': 5},
    {'route_beam_width': 0}, {'unknown_combat_probability': 2}, {'seed': True}, {'typo': 1}])
def test_bad_bot_configuration(overrides):
    with pytest.raises(ValueError): load_policy_config(**overrides)


def card_observation(request_data):
    return dict(runId='policy-test', decisionSeq=1, screen='CARD_REWARD', context=None,
        state=dict(act=1, actId='OVERGROWTH', hp=70, maxHp=70, gold=99, floor=6,
                   build=request_data['build'], visibleBoss='VANTOM_BOSS', floorsToBoss=3,
                   currentNode={'row': 1, 'col': 0}, map=[], potions=[]),
        options=[dict(index=i, kind='card', action='take', card=dict(c, unsupported_fields=[]))
                 for i, c in enumerate(request_data['rewards'])] + [dict(index=3, kind='alternative', id='Skip')])


def test_full_card_policy_enforces_margin_and_forced_selection(request_data):
    observation = card_observation(request_data)
    bot = BotPolicy(FakeScorer(), config={'normal_card_min_gain': 4, 'max_rollout_depth': 0})
    assert bot.choose(observation) == 3  # FOOTWORK is exactly +4, not strictly above.
    assert not bot.last_report['crisis']
    observation['options'].pop()
    assert bot.choose(observation) == 0  # Forced choice cannot invent a skip.


def test_crisis_expands_actual_search_and_relaxes_margin(request_data):
    observation = card_observation(request_data)
    bot = BotPolicy(FakeScorer(), config={'normal_card_min_gain': 10, 'max_rollout_depth': 1,
        'crisis_boss_loss_fraction': .1, 'crisis_samples_per_parent': 36, 'crisis_keep_per_parent': 6})
    assert bot.choose(observation) == 0
    assert bot.last_report['crisis']
    assert bot.last_report['samples_per_parent'] == 36
    assert bot.last_report['stats']['per_depth'][0]['leaves_per_root'] == [6]*4


def test_blocked_card_does_not_hide_other_legal_alternative(request_data):
    observation = card_observation(request_data)
    observation['state']['hp'] = 69
    observation['options'].append(dict(index=4, kind='alternative', id='Heal'))
    bot = BotPolicy(FakeScorer(), config={'normal_card_min_gain': 4, 'max_rollout_depth': 0})
    assert bot.choose(observation) == 4
    assert bot.last_report['threshold_rejected'] == [0, 1, 2]


@pytest.mark.parametrize('screen', ['CARD_REWARD', 'CHOOSE_CARD', 'CARD_GRID'])
def test_optional_reward_and_event_cards_share_threshold(request_data, screen):
    observation = card_observation(request_data)
    observation.update(screen=screen, context={'action': 'take'})
    bot = BotPolicy(FakeScorer(), config={'normal_card_min_gain': 4, 'max_rollout_depth': 0})
    assert bot.choose(observation) == 3


def test_shop_margin_is_independent_of_gold_cost_and_reserve(request_data):
    observation = card_observation(request_data)
    observation.update(screen='SHOP')
    observation['state']['gold'] = 0
    observation['options'][-1] = dict(index=3, kind='leave')
    for option in observation['options'][:-1]: option['price'] = 0
    bot = BotPolicy(FakeScorer(), config={'normal_card_min_gain': 4, 'max_rollout_depth': 0,
                                        'gold_hp_value': 0, 'shop_reserve_gold': 50})
    assert bot.choose(observation) == 3
    assert bot.last_report['scores'][3] == 0


def test_shop_buys_worthwhile_card_before_higher_scoring_potion(request_data):
    observation = card_observation(request_data)
    observation.update(screen='SHOP')
    observation['state'].update(gold=500, potions=[dict(id=None)])
    # This fixture has no reachable short-term encounters: gain is .65 * 4.
    card = dict(observation['options'][0], price=250)
    observation['options'] = [card, dict(index=1, kind='potion', id='WEAK_POTION', price=50),
                              dict(index=2, kind='leave')]
    bot = BotPolicy(FakeScorer(), config={'max_rollout_depth': 0})
    assert bot.choose(observation) == 0
    assert bot.last_report['scores'][0] == pytest.approx(.1)
    assert bot.last_report['scores'][1] == pytest.approx(.5)
    assert bot.last_report['potions_deferred_for_cards'] == [1]
    # After the card purchase the same shop is scored again with remaining gold.
    observation['state']['gold'] = 250
    observation['options'] = [dict(index=0, kind='potion', id='WEAK_POTION', price=50),
                              dict(index=1, kind='leave')]
    assert bot.choose(observation) == 0
    observation['state']['potions'] = [dict(id='WEAK_POTION')]
    assert bot.choose(observation) == 1


@pytest.mark.parametrize('price,margin', [(450, 1), (0, 4)])
def test_unworthy_cards_do_not_block_potion_purchase(request_data, price, margin):
    observation = card_observation(request_data)
    observation.update(screen='SHOP')
    observation['state'].update(gold=500, potions=[dict(id=None)])
    observation['options'] = [dict(observation['options'][0], price=price),
                              dict(index=1, kind='potion', id='WEAK_POTION', price=50),
                              dict(index=2, kind='leave')]
    bot = BotPolicy(FakeScorer(), config={'max_rollout_depth': 0, 'normal_card_min_gain': margin})
    assert bot.choose(observation) == 1
    assert bot.last_report['potions_deferred_for_cards'] == []


def test_route_risk_and_hidden_payload_independence():
    state = dict(hp=15, maxHp=70, gold=0, map=[
        dict(row=1, col=0, type='Elite', children=[dict(row=2, col=0)]),
        dict(row=1, col=1, type='RestSite', children=[dict(row=2, col=0)]),
        dict(row=2, col=0, type='Boss', children=[])])
    options = [dict(index=0, row=1, col=0), dict(index=1, row=1, col=1)]
    losses = dict(Monster=4, Elite=20, Boss=20)
    result = plan_route(state, options, losses, load_policy_config())
    assert result[0] == 1
    state['future_encounters'] = ['CHEATING_PAYLOAD']
    state['rng'] = {'seed': 999}
    assert plan_route(state, options, losses, load_policy_config()) == result


def test_event_lethal_options_override_model_score(request_data):
    observation = card_observation(request_data)
    relic = request_data['build']['relics'][-1]
    observation.update(screen='EVENT', context={'eventId': 'RELIC_TRADER'}, options=[
        dict(index=0, kind='relic', relic=relic, lethal=True),
        dict(index=1, kind='event', id='LEAVE', proceed=True)])
    assert BotPolicy(FakeScorer()).choose(observation) == 1


@pytest.mark.parametrize('screen', ['REWARDS', 'TREASURE', 'RELIC'])
def test_free_relic_is_taken_without_model_scoring(request_data, screen):
    observation = card_observation(request_data)
    observation.update(screen=screen, options=[dict(index=0, kind='skip'),
        dict(index=1, kind='relic', relic=dict(id='NUNCHAKU', state=[['AttacksPlayed', 103]]))])
    scorer = FakeScorer()
    def forbidden(*args, **kwargs): raise AssertionError('Free relic must not invoke model scoring')
    scorer.score_many = forbidden
    bot = BotPolicy(scorer)
    assert bot.choose(observation) == 1
    assert bot.last_report['reason'] == 'take_free_relic'


def test_exclusive_relic_choices_still_compare_instant_strength(request_data):
    observation = card_observation(request_data)
    observation.update(screen='RELIC', options=[dict(index=0, kind='relic', relic=dict(id='VAJRA', state=[])),
        dict(index=1, kind='relic', relic=dict(id='ANCHOR', state=[])), dict(index=2, kind='skip')])
    scorer = FakeScorer()
    def score(requests, **kwargs):
        return [dict(expected_hp_loss=10-(3 if any(r['id']=='ANCHOR' for r in q['build']['relics']) else 0),
                     warnings=[], untrained_features=[]) for q in requests]
    scorer.score_many = score
    bot = BotPolicy(scorer)
    assert bot.choose(observation) == 1
    assert bot.last_report['reason'] == 'immediate_model_and_visible_resources'


def test_map_options_do_not_require_reward_kind(request_data):
    observation = card_observation(request_data)
    observation.update(screen='MAP', options=[dict(index=0, row=1, col=0), dict(index=1, row=1, col=1)])
    observation['state']['map'] = [dict(row=1, col=0, type='Monster', children=[]),
                                   dict(row=1, col=1, type='Boss', children=[])]
    assert BotPolicy(FakeScorer()).choose(observation) == 0


def test_owned_sea_glass_character_title_alias_preserves_provenance(request_data):
    from copy import deepcopy
    from runctl.model_adapter import ModelAdapter
    raw = deepcopy(request_data['build'])
    raw.update(act=2, act_id='HIVE')
    raw['ancient_history'] = list(raw['ancient_history']) + [[2, 'OROBAS', 'DEFECT']]
    raw['relics'] = list(raw['relics']) + [dict(id='SEA_GLASS', state=[], unsupported_fields=['CharacterId'])]
    original = deepcopy(raw)
    adapter = ModelAdapter(FakeScorer())
    projected = adapter.project(raw)
    assert projected.ancient_history[-1] == (2, 'OROBAS', 'SEA_GLASS')
    assert all(r.id != 'SEA_GLASS' for r in projected.relics)
    assert 'ancient_history_alias:DEFECT:SEA_GLASS' in adapter.warnings
    assert raw == original
    raw['relics'].pop()
    with pytest.raises(ValueError, match='Illegal ancient provenance'):
        adapter.project(raw)


@pytest.mark.parametrize('description', ['失去 6 点最大生命。升级一张牌。', 'Lose 6 Max HP. Upgrade a card.'])
def test_tablet_max_hp_cost_is_not_mistaken_for_free_upgrade(description):
    config = load_policy_config()
    state = dict(hp=50, maxHp=70)
    value, reason = event_value('TABLET_OF_TRUTH', dict(id='DECIPHER', description=description), state, config)
    assert value == -1 and reason == 'tablet_displayed_escalating_max_hp_cost'


def test_max_hp_loss_also_accounts_for_current_hp_clamp():
    config = load_policy_config()
    full = dict(hp=70, maxHp=70)
    value, _ = event_value('ANY', dict(description='失去 10 点最大生命。'), full, config)
    assert value == -20


def test_wellspring_and_unrest_include_named_curse_cost():
    config = load_policy_config()
    state = dict(hp=20, maxHp=70, potions=[dict(id=None)])
    bottle = event_value('WELLSPRING', dict(id='BOTTLE'), state, config)[0]
    bathe = event_value('WELLSPRING', dict(id='BATHE', description='移除一张牌。获得愧疚。'), state, config)[0]
    assert bottle == config['potion_value'] and bathe < 0
    unrest = event_value('UNREST_SITE', dict(id='REST', description='恢复 50 点生命。获得睡眠不佳。'), state, config)[0]
    assert unrest == pytest.approx(50*(1+2*(1-20/70))-config['event_curse_cost'])


def test_visible_event_health_and_gold_costs():
    state = dict(hp=20, maxHp=70)
    config = load_policy_config()
    heal, _ = event_value('WELLSPRING', dict(description='恢复 10 点生命。失去 20 金币。'), state, config)
    damage, _ = event_value('WELLSPRING', dict(description='失去 10 点生命。获得 20 金币。'), state, config)
    assert heal > 0 and damage < 0
    assert event_value('ANY', dict(lethal=True), state, config)[0] < -1e8


def test_batch_summary_keeps_failures_out_of_death_count():
    episodes = [dict(outcome='death', state=dict(floor=11, act=1)),
                dict(outcome='victory', state=dict(floor=50, act=3))]
    summary = summarize([dict(returncode=0, episodes=episodes), dict(returncode=1, episodes=[])], 4)
    assert summary['completed'] == 2 and summary['deaths'] == 1 and summary['wins'] == 1
    assert summary['failed_workers'] == 1 and summary['requested'] == 4
    assert summary['win_rate'] == .5 and summary['mean_floor'] == 30.5


def test_short_horizon_uses_public_weak_count_without_peeking_unknown_room():
    state = dict(normalCombatsCompleted=2, currentNode=dict(row=0, col=0), map=[
        dict(row=0, col=0, type='Monster', children=[dict(row=1, col=0)]),
        dict(row=1, col=0, type='Unknown', children=[dict(row=2, col=0)]),
        dict(row=2, col=0, type='Monster', children=[])])
    floors = next_floors(state, lambda room, count: {'weak' if count < 3 else 'strong': 1}, .25)
    assert floors[0] == dict(targets={'weak': .25}, combat_probability=.25)
    assert floors[1] == dict(targets={'strong': .25, 'weak': .75}, combat_probability=1)


def test_short_horizon_extends_past_two_noncombat_rooms():
    state = dict(normalCombatsCompleted=0, currentNode=dict(row=0, col=0), map=[
        dict(row=0, col=0, type='Monster', children=[dict(row=1, col=0)]),
        dict(row=1, col=0, type='Shop', children=[dict(row=2, col=0)]),
        dict(row=2, col=0, type='RestSite', children=[dict(row=3, col=0)]),
        dict(row=3, col=0, type='Unknown', children=[dict(row=4, col=0)]),
        dict(row=4, col=0, type='Boss', children=[])])
    targets = lambda room, count: {room: 1}
    assert next_floors(state, targets, .25) == [dict(targets={'Monster': .25}, combat_probability=.25)]
    assert next_floors(state, targets, 0) == [dict(targets={'Boss': 1}, combat_probability=1)]


def test_orobas_candidate_projects_deterministic_starter_replacement(request_data):
    from copy import deepcopy
    raw = deepcopy(request_data['build'])
    raw.update(act=2, act_id='HIVE')
    original = deepcopy(raw)
    bot = BotPolicy(FakeScorer())
    candidate = bot.candidate(raw, dict(kind='relic', relic=dict(id='TOUCH_OF_OROBAS', state=[],
        unsupported_fields=['StarterRelic', 'UpgradedRelic'])), {'eventId': 'OROBAS'})
    ids = [r.id for r in candidate.relics]
    assert ids[0] == 'RING_OF_THE_DRAKE' and 'RING_OF_THE_SNAKE' not in ids
    assert 'TOUCH_OF_OROBAS' in ids and raw == original


def test_removal_of_projected_out_card_never_aliases_an_owned_instance(request_data):
    observation = card_observation(request_data)
    cards = observation['state']['build']['cards']
    cards.insert(0, dict(id='ALCHEMIZE'))
    cards.append(dict(id='FOOTWORK'))
    observation.update(screen='CARD_GRID', context=dict(action='remove'), options=[
        dict(index=0, kind='card', action='remove', card=cards[0], deckIndex=0),
        dict(index=1, kind='card', action='remove', card=cards[-1], deckIndex=len(cards)-1)])
    bot = BotPolicy(FakeScorer(), config={'max_rollout_depth': 0})
    assert bot.choose(observation) == 0
    assert 'unscored_remove:ALCHEMIZE' in bot.last_report['warnings']
    assert bot.last_report['scores'][0] > bot.last_report['scores'][1]


def test_enchantment_candidate_stacks_and_does_not_mutate_owned_card(request_data):
    from copy import deepcopy
    raw = deepcopy(request_data['build'])
    raw['cards'][0].update(enchantment_id='SHARP', enchantment_amount=2)
    original = deepcopy(raw)
    bot = BotPolicy(FakeScorer())
    result = bot.candidate(raw, dict(kind='card', action='enchant', deckIndex=0),
                           {'effect': dict(id='SHARP', amount=3)})
    assert result.cards[0].enchantment_amount == 5 and raw == original
    with pytest.raises(ValueError, match='different existing enchantment'):
        bot.candidate(raw, dict(kind='card', action='enchant', deckIndex=0),
                      {'effect': dict(id='SLITHER', amount=1)})
