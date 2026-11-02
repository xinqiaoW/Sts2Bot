import pytest

from runctl.event_policy import doll_room_options
from runctl.policy import BotPolicy
from test_bot_policy import card_observation
from test_reward_policy import FakeScorer, request_data


def test_initial_uses_named_second_option_even_after_reordering():
    options = [dict(index=i, id='DOLL_ROOM.pages.INITIAL.options.' + name)
               for i, name in enumerate(['RANDOM', 'TAKE_SOME_TIME', 'EXAMINE'])]
    assert doll_room_options(options)[0] == [options[1]]
    assert doll_room_options(list(reversed(options)))[0] == [options[1]]
    options[1]['lethal'] = True
    with pytest.raises(ValueError, match='lethal'):
        doll_room_options(options)


@pytest.mark.parametrize('banned', [dict(relic={'id': 'BING_BONG'}),
    dict(id='宾邦', relic=None), dict(id='Bing Bong'), dict(title='[gold]宾邦[/gold]'), dict(id='BING_BONG')])
@pytest.mark.parametrize('position', [0, 1])
def test_bing_bong_is_excluded_before_model_scoring(request_data, banned, position):
    observation = card_observation(request_data)
    options = [dict(id='风的女儿', kind='event', relic=None)]
    options.insert(position, dict(kind='event', **banned))
    options = [dict(o, index=i) for i, o in enumerate(options)]
    observation.update(screen='EVENT', context={'eventId': 'DOLL_ROOM'}, options=options)
    bot = BotPolicy(FakeScorer())
    def forbidden(*args, **kwargs):
        raise AssertionError('A forced event choice must not need model scoring')
    bot.model.score = forbidden
    assert bot.choose(observation) == 1-position
    assert bot.last_report['reason'] == 'doll_room_exclude_bing_bong'


def test_single_option_cannot_bypass_ban_and_proceed_still_works(request_data):
    observation = card_observation(request_data)
    observation.update(screen='EVENT', context={'eventId': 'DOLL_ROOM'},
                       options=[dict(index=0, kind='event', id='宾邦')])
    bot = BotPolicy(FakeScorer())
    with pytest.raises(ValueError, match='forbidden'):
        bot.choose(observation)
    observation['options'] = [dict(index=0, kind='event', id='PROCEED', proceed=True)]
    assert bot.choose(observation) == 0


def test_two_safe_dolls_remain_available_and_unknown_page_fails():
    options = [dict(index=0, id='风的女儿'), dict(index=1, title='Mr. Struggles')]
    assert doll_room_options(options)[0] == options
    with pytest.raises(ValueError, match='recognized safe'):
        doll_room_options([dict(index=0, id='UNKNOWN')])
