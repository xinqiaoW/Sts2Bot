from copy import deepcopy

import pytest

from runctl.policy import BotPolicy
from runctl.policy_config import load_policy_config, potion_priority
from test_reward_policy import FakeScorer, request_data
from test_bot_policy import card_observation

ORDER = ['FAIRY_IN_A_BOTTLE', 'AMBERGRIS', 'SHIP_IN_A_BOTTLE', 'HEART_OF_IRON', 'GAMBLERS_BREW',
         'GHOST_IN_A_JAR', 'FORTIFIER', 'STABLE_SERUM', 'BLOCK_POTION', 'DEXTERITY_POTION',
         'SWIFT_POTION', 'POWER_POTION', 'OROBIC_ACID', 'CURE_ALL', 'ENERGY_POTION']


def observation(request_data, held, drops):
    obs = card_observation(request_data)
    obs.update(screen='REWARDS', options=[])
    obs['state']['potions'] = [dict(slot=i, id=p) for i, p in enumerate(held)]
    for incoming in drops:
        if None in held:
            obs['options'].append(dict(kind='potion', id=incoming))
        else:
            obs['options'].extend(dict(kind='potion_replace', id=incoming, discardSlot=i, discardId=p)
                                  for i, p in enumerate(held))
    obs['options'].append(dict(kind='leave'))
    for i, option in enumerate(obs['options']):
        option['index'] = i
    return obs


def test_exact_user_order():
    c = load_policy_config()
    assert c['potion_priority'] == ORDER
    assert [potion_priority(p, c) for p in ORDER] == list(range(15, 0, -1))
    assert potion_priority('FRUIT_JUICE', c) == potion_priority('FIRE_POTION', c) == 0


@pytest.mark.parametrize('bad', [None, {}, 'FAIRY_IN_A_BOTTLE', [1], [''], ['fairy'], ['X','X']])
def test_invalid_config(bad):
    with pytest.raises(ValueError, match='potion_priority'):
        load_policy_config(potion_priority=bad)


@pytest.mark.parametrize('held,new,slot', [
    (['FIRE_POTION','BLOCK_POTION'], 'ENERGY_POTION', 0),
    (['FAIRY_IN_A_BOTTLE','ENERGY_POTION'], 'GHOST_IN_A_JAR', 1),
    (['GHOST_IN_A_JAR','GAMBLERS_BREW'], 'HEART_OF_IRON', 0),
    (['FIRE_POTION','WEAK_POTION'], 'BLOCK_POTION', 0),
    (['BLOCK_POTION','BLOCK_POTION'], 'FAIRY_IN_A_BOTTLE', 0),
    (['FAIRY_IN_A_BOTTLE','AMBERGRIS'], 'SHIP_IN_A_BOTTLE', None),
    (['ENERGY_POTION','ENERGY_POTION'], 'ENERGY_POTION', None),
    (['FIRE_POTION','WEAK_POTION'], 'FRUIT_JUICE', None),
])
def test_replace_only_lowest_and_strictly_better(request_data, held, new, slot):
    bot = BotPolicy(FakeScorer())
    obs = observation(request_data, held, [new])
    before = deepcopy(obs)
    chosen = obs['options'][bot.choose(obs)]
    if slot is None:
        assert chosen['kind'] == 'leave'
    else:
        assert chosen['kind'] == 'potion_replace' and chosen['discardSlot'] == slot
        assert chosen['id'] == new
    assert obs == before
    assert bot.last_report['reason'] == 'potion_priority'


def test_free_slot_takes_highest_drop_and_does_not_require_model(request_data):
    bot = BotPolicy(FakeScorer())
    def no_model(*args, **kwargs):
        raise AssertionError('Potion-only rewards must not run the deck model')
    bot.model.scorer.score_many = no_model
    obs = observation(request_data, ['FAIRY_IN_A_BOTTLE',None], ['FIRE_POTION','ENERGY_POTION','AMBERGRIS'])
    chosen = obs['options'][bot.choose(obs)]
    assert chosen['kind'] == 'potion' and chosen['id'] == 'AMBERGRIS'
    obs = observation(request_data, [None], ['FIRE_POTION'])
    assert obs['options'][bot.choose(obs)]['kind'] == 'potion'


def test_config_override_and_multiple_sequential_drops(request_data):
    bot = BotPolicy(FakeScorer(), config=dict(potion_priority=['ENERGY_POTION','FIRE_POTION']))
    obs = observation(request_data, ['FAIRY_IN_A_BOTTLE','WEAK_POTION'], ['FIRE_POTION','ENERGY_POTION'])
    chosen = obs['options'][bot.choose(obs)]
    assert chosen['id'] == 'ENERGY_POTION' and chosen['discardSlot'] == 0
    obs = observation(request_data, ['ENERGY_POTION','WEAK_POTION'], ['FIRE_POTION'])
    chosen = obs['options'][bot.choose(obs)]
    assert chosen['id'] == 'FIRE_POTION' and chosen['discardSlot'] == 1


def test_mixed_rewards_uses_same_replacement_rule(request_data):
    bot = BotPolicy(FakeScorer())
    obs = observation(request_data, ['FAIRY_IN_A_BOTTLE','ENERGY_POTION'], ['GHOST_IN_A_JAR'])
    obs['options'].append(dict(index=len(obs['options']), kind='gold', amount=1))
    assert obs['options'][bot.choose(obs)]['discardSlot'] == 1
    assert bot.last_report['potion_choice']['id'] == 'GHOST_IN_A_JAR'


def test_missing_or_stale_slot_is_not_accepted(request_data):
    bot = BotPolicy(FakeScorer())
    obs = observation(request_data, ['FIRE_POTION'], ['FAIRY_IN_A_BOTTLE'])
    obs['options'][0]['discardId'] = 'WEAK_POTION'
    assert obs['options'][bot.choose(obs)]['kind'] == 'leave'
    obs['options'] = obs['options'][:1]
    with pytest.raises(ValueError, match='No eligible'):
        bot.choose(obs)
