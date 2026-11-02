from copy import deepcopy

import pytest

from runctl.policy import BotPolicy
from runctl.event_policy import event_card_addition, event_health_delta
from test_reward_policy import FakeScorer, request_data
from test_bot_policy import card_observation


def option(index, key, description='', **extra):
    return dict(index=index, kind='event', id=key, description=description, **extra)


def observation(data, event, options, hp=70):
    obs = card_observation(data)
    obs.update(screen='EVENT', context=dict(eventId=event), options=options)
    obs['state'].update(hp=hp, actFloor=8)
    return obs


def test_safe_spirit_declines_unhelpful_card_despite_heal(request_data):
    obs = observation(request_data, 'SPIRIT_GRAFTER', [
        option(0, 'LET_IT_IN', '回复20点生命。将一张羽化添加到你的牌组。'),
        option(1, 'REJECTION', '失去8点生命。升级一张牌。')], hp=60)
    bot = BotPolicy(FakeScorer())
    assert bot.choose(obs) == 1
    assert bot.last_report['event_rejected_options'] == [0]
    assert bot.last_report['event_combat']['weighting']['basis'] == 'survival_budget'


@pytest.mark.parametrize('event,key,count', [('ROOM_FULL_OF_CHEESE', 'GORGE', 2),
                                           ('BRAIN_LEECH', 'SHARE_KNOWLEDGE', 1)])
def test_safe_deck_avoids_unknown_forced_grid(request_data, event, key, count):
    obs = observation(request_data, event, [option(0, key, '选择卡牌加入牌组'),
        option(1, 'SEARCH', '失去5点生命。')])
    bot = BotPolicy(FakeScorer())
    assert bot.choose(obs) == 1
    detail = bot.last_report['event_combat']['evaluations'][0]
    assert detail['addition'] == dict(count=count, cards=None)
    assert detail['combat_gain'] is None


def test_unsafe_alternative_does_not_force_hp_payment(request_data):
    obs = observation(request_data, 'ROOM_FULL_OF_CHEESE', [option(0, 'GORGE'),
        option(1, 'SEARCH', '失去20点生命。')], hp=35)
    bot = BotPolicy(FakeScorer())
    assert bot.choose(obs) == 0
    assert not bot.last_report['event_rejected_options']


def test_lethal_alternative_never_used_to_avoid_cards(request_data):
    obs = observation(request_data, 'SPIRIT_GRAFTER', [option(0, 'LET_IT_IN', '回复20点生命。'),
        option(1, 'REJECTION', '失去8点生命。升级一张牌。', lethal=True)], hp=5)
    bot = BotPolicy(FakeScorer())
    assert bot.choose(obs) == 0


def test_enlightenment_preview_means_two_copies():
    addition = event_card_addition('ZEN_WEAVER', option(0, 'BREATHING_TECHNIQUES',
        cards=[dict(deckIndex=-1, card=dict(id='ENLIGHTENMENT', upgrade=0))]))
    assert addition['cards'] == [dict(id='ENLIGHTENMENT', upgrade=0)]*2


def test_two_card_model_scores_complete_bundle_and_preserves_input(request_data):
    class Recording(FakeScorer):
        def __init__(self):
            super().__init__()
            self.counts = []
        def score_many(self, requests, strict=False):
            self.counts.extend(sum(c['id']=='ENLIGHTENMENT' for c in r['build']['cards']) for r in requests)
            return super().score_many(requests, strict)
    scorer = Recording()
    obs = observation(request_data, 'ZEN_WEAVER', [option(0, 'BREATHING_TECHNIQUES', '支付50金币。'),
        option(1, 'EMOTIONAL_AWARENESS', '支付50金币。移除一张牌。')])
    original = deepcopy(obs)
    bot = BotPolicy(scorer)
    assert bot.choose(obs) == 1
    assert 2 in scorer.counts
    assert obs == original


def test_safe_known_beneficial_addition_can_still_win(request_data):
    obs = observation(request_data, 'BYRDONIS_NEST', [option(0, 'TAKE', cards=[
        dict(deckIndex=-1, card=dict(id='FOOTWORK'))]), option(1, 'EAT')])
    bot = BotPolicy(FakeScorer())
    assert bot.choose(obs) == 0
    assert bot.last_report['event_combat']['evaluations'][0]['combat_gain'] == pytest.approx(2.88)


def bridge(data, card='FOOTWORK', hp=70, cost=3):
    obs = observation(data, 'SLIPPERY_BRIDGE', [], hp=hp)
    cards = obs['state']['build']['cards']
    cards.append(dict(id=card))
    obs['options'] = [option(0, 'OVERCOME', cards=[dict(deckIndex=len(cards)-1, card=deepcopy(cards[-1]))]),
                      option(1, 'HOLD_ON_0', f'失去[red]{cost}[/red]点生命。重新随机上方选项中的卡牌。')]
    return obs


def test_bridge_protects_key_card_and_then_accepts_filler(request_data):
    bot = BotPolicy(FakeScorer())
    obs = bridge(request_data)
    assert bot.choose(obs) == 1
    report = bot.last_report['event_combat']['evaluations'][0]
    assert report['critical'] and report['worst_loss_increase'] == 4
    assert report['safe_hold_options'] == [1]
    # Next displayed roll is a basic card; no stale protection attaches to it.
    obs['options'][0]['cards'] = [dict(deckIndex=0, card=deepcopy(obs['state']['build']['cards'][0]))]
    obs['state']['hp'] -= 3
    assert bot.choose(obs) == 0


@pytest.mark.parametrize('hp,cost', [(28, 3), (70, 44), (2, 3)])
def test_bridge_stops_reroll_before_budget_exhaustion(request_data, hp, cost):
    bot = BotPolicy(FakeScorer())
    assert bot.choose(bridge(request_data, hp=hp, cost=cost)) == 0
    assert bot.last_report['event_combat']['evaluations'][0]['safe_hold_options'] == []


def test_bridge_holds_no_extra_arbitrary_penalty(request_data):
    bot = BotPolicy(FakeScorer())
    bot.choose(bridge(request_data))
    assert bot.last_report['scores'][1] == -3


def test_bridge_unknown_instance_is_protected_not_scored_as_free_removal(request_data):
    obs = bridge(request_data, card='NOT_IN_CATALOG')
    bot = BotPolicy(FakeScorer())
    assert bot.choose(obs) == 1
    assert bot.last_report['event_combat']['evaluations'][0]['worst_loss_increase'] is None


def test_bridge_missing_preview_does_not_blindly_remove(request_data):
    obs = bridge(request_data)
    obs['options'][0]['cards'] = []
    assert BotPolicy(FakeScorer()).choose(obs) == 1


def test_bridge_wrong_owned_instance_rejected(request_data):
    obs = bridge(request_data)
    obs['options'][0]['cards'][0]['deckIndex'] = 0
    with pytest.raises(ValueError, match='preview differs'):
        BotPolicy(FakeScorer()).choose(obs)


def test_bridge_uses_long_target_even_when_short_monsters_are_easy(request_data):
    class BossKey(FakeScorer):
        def score_many(self, requests, strict=False):
            results = super().score_many(requests, strict)
            for request, result in zip(requests, results):
                present = any(c['id']=='FOOTWORK' for c in request['build']['cards'])
                result['expected_hp_loss'] = sum(w*(5 if target!='VANTOM_BOSS' else 10 if present else 30)
                    for target,w in request['targets'].items()) / sum(request['targets'].values())
            return results
    bot = BotPolicy(BossKey())
    obs = bridge(request_data)
    obs['state'].update(normalCombatsCompleted=5, currentNode=dict(row=0,col=0),
        map=[dict(row=0,col=0,type='Event',children=[dict(row=1,col=0)]),
             dict(row=1,col=0,type='Monster',children=[])])
    assert bot.choose(obs) == 1
    row = bot.last_report['event_combat']['evaluations'][0]
    assert row['worst_loss_increase'] == 20
    assert row['after']['short_expected_hp_loss'] == 5


def test_bridge_threshold_is_configurable(request_data):
    obs = bridge(request_data, cost=10)
    assert BotPolicy(FakeScorer()).choose(obs) == 1
    assert BotPolicy(FakeScorer(), config={'bridge_key_card_loss_threshold': 5}).choose(obs) == 0


@pytest.mark.parametrize('description,expected', [('回复[green]20[/green]点生命。', 10),
    ('失去[red]3[/red]点生命。', -3), ('Lose 3 HP.', -3), ('失去10点最大生命。', 0)])
def test_event_health_delta(description, expected):
    assert event_health_delta(option(0,'X',description),dict(hp=60,maxHp=70)) == expected


def test_incidental_hover_and_optional_reward_are_not_forced_addition():
    for event, key in [('OROBAS','RADIANT_PEARL'),('BRAIN_LEECH','RIP'),('TRIAL','GUILTY')]:
        assert event_card_addition(event, option(0,key,cards=[dict(deckIndex=-1,card=dict(id='FOOTWORK'))])) is None


def test_bridge_double_boss_uses_max_loss_but_sum_for_budget(request_data):
    from test_double_boss_target import SwitchingBossScorer, state
    scorer = SwitchingBossScorer()
    obs = bridge(request_data)
    obs['state'].update(state(scorer))
    bot = BotPolicy(scorer)
    assert bot.choose(obs) == 1
    report = bot.last_report['event_combat']
    assert report['baseline']['long_expected_hp_loss'] == 30
    assert report['evaluations'][0]['after']['long_expected_hp_loss'] == 40
    assert report['weighting']['survival_budget']['target_expected_hp_loss'] == 35


def test_bridge_duplicate_cards_remove_exact_upgrade_instance(request_data):
    class UpgradedKey(FakeScorer):
        def score_many(self, requests, strict=False):
            results = super().score_many(requests, strict)
            for request, result in zip(requests, results):
                result['expected_hp_loss'] = 10 if any(c['id']=='FOOTWORK' and c.get('upgrade')==1
                    for c in request['build']['cards']) else 25
            return results
    obs = bridge(request_data)
    obs['state']['build']['cards'].append(dict(id='FOOTWORK', upgrade=1))
    bot = BotPolicy(UpgradedKey())
    assert bot.choose(obs) == 0  # Offered unupgraded instance is dispensable.
    obs['options'][0]['cards'] = [dict(deckIndex=len(obs['state']['build']['cards'])-1,
                                       card=dict(id='FOOTWORK', upgrade=1))]
    assert bot.choose(obs) == 1


def test_weak_spirit_can_use_healing_without_sufficient_combat_veto(request_data):
    obs = observation(request_data, 'SPIRIT_GRAFTER', [option(0, 'LET_IT_IN', '回复20点生命。'),
        option(1, 'REJECTION', '失去8点生命。升级一张牌。')], hp=20)
    bot = BotPolicy(FakeScorer())
    assert bot.choose(obs) == 0
    assert bot.last_report['event_combat']['weighting']['mode'] == 'insufficient'
    assert bot.last_report['event_rejected_options'] == []


def test_bridge_large_removal_penalty_cannot_force_unsafe_reroll(request_data):
    class Critical(FakeScorer):
        def score_many(self, requests, strict=False):
            return [dict(expected_hp_loss=10 if any(c['id']=='FOOTWORK' for c in r['build']['cards']) else 60,
                         warnings=[], untrained_features=[]) for r in requests]
    bot = BotPolicy(Critical())
    assert bot.choose(bridge(request_data, hp=12)) == 0
    assert bot.last_report['event_rejected_options'] == [1]
