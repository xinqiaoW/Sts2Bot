import pytest
from runctl.policy import BotPolicy
from runctl.event_policy import forbidden_event_reward
from test_reward_policy import FakeScorer, request_data
from test_bot_policy import card_observation


@pytest.mark.parametrize('data', [dict(relic=dict(id='STORYBOOK')), dict(id='DARV.pages.INITIAL.options.STORYBOOK')])
@pytest.mark.parametrize('index',[0,1])
def test_storybook_banned_before_scoring(request_data,data,index):
    obs=card_observation(request_data)
    options=[dict(kind='event',id='LEAVE',proceed=True)]
    options.insert(index,dict(kind='relic',**data))
    obs.update(screen='EVENT',context=dict(eventId='DARV'),options=[dict(o,index=i) for i,o in enumerate(options)])
    bot=BotPolicy(FakeScorer())
    def fail(*args,**kwargs):raise AssertionError('Should not score the forbidden reward')
    bot.model.score=fail
    assert bot.choose(obs)==1-index
    assert bot.last_report['forbidden_event_options']==[index]


def test_single_forbidden_option_cannot_bypass_ban(request_data):
    obs=card_observation(request_data)
    obs.update(screen='EVENT',context=dict(eventId='DARV'),options=[dict(index=0,kind='relic',relic=dict(id='STORYBOOK'))])
    with pytest.raises(ValueError,match='reward is forbidden'):
        BotPolicy(FakeScorer()).choose(obs)


@pytest.mark.parametrize('data', [dict(relic=dict(id='NEOWS_SACRIFICE')),
                                dict(id='NEOW.pages.INITIAL.options.NEOWS_SACRIFICE')])
def test_neow_ambergris_offer_banned(request_data, data):
    obs = card_observation(request_data)
    obs.update(screen='EVENT', context=dict(eventId='NEOW'), options=[
        dict(index=0, kind='event', **data), dict(index=1, kind='event', id='LEAVE', proceed=True)])
    assert BotPolicy(FakeScorer()).choose(obs) == 1
    obs['options'] = obs['options'][:1]
    with pytest.raises(ValueError, match='reward is forbidden'):
        BotPolicy(FakeScorer()).choose(obs)


def test_ambergris_potion_is_not_banned():
    assert not forbidden_event_reward(dict(kind='potion', id='AMBERGRIS'))


def test_other_relics_and_unrelated_hover_remain_allowed():
    assert not forbidden_event_reward(dict(relic=dict(id='RUNIC_PYRAMID')))
    assert not forbidden_event_reward(dict(id='PROCEED',cards=[dict(card=dict(id='BRIGHTEST_FLAME'))]))


def test_brightest_flame_already_excluded_from_ordinary_rollout():
    from train.reward_policy import RewardSelector
    assert 'BRIGHTEST_FLAME' not in RewardSelector(FakeScorer()).pool()
