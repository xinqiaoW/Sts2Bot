"""Worst remaining Boss per build, without changing short-term battle mixtures."""
from copy import deepcopy

import pytest

from train.reward_policy import RewardSelector
from train.scoring_horizon import scoring_horizon
from train.advisor_service import evaluate
from runctl.policy import BotPolicy
from test_reward_policy import request_data
from test_scoring_horizon import PoolScorer, coverage
from test_bot_policy import card_observation
from test_advisor_service import payload


class SwitchingBossScorer(PoolScorer):
    def __init__(self):
        super().__init__()
        self.bosses = [e['id'] for e in self.catalog.acts['OVERGROWTH']['encounters'] if e['room_type'] == 'Boss'][:2]

    def value(self, build, target):
        cards = [c['id'] for c in build['cards']]
        # The base deck fears Boss A (40 vs 10). Footwork makes Boss B
        # harder (5 vs 30); Backflip is balanced (25 vs 25).
        pair = (25, 25) if 'BACKFLIP' in cards else (5, 30) if 'FOOTWORK' in cards else (40, 10)
        return pair[self.bosses.index(target)] if target in self.bosses else 8

    def score_many(self, requests, strict=False):
        self.requests.extend(deepcopy(requests))
        return [dict(expected_hp_loss=sum(w*self.value(r['build'], t) for t, w in r['targets'].items()) /
                     sum(r['targets'].values()), warnings=[], untrained_features=[]) for r in requests]


def state(scorer):
    return dict(actId='OVERGROWTH', act=1, actFloor=7, normalCombatsCompleted=3,
                visibleBoss=scorer.bosses[0], remainingBosses=scorer.bosses)


def test_remaining_bosses_before_after_and_legacy():
    s = SwitchingBossScorer()
    st = state(s)
    h = scoring_horizon(s.catalog, coverage(s.catalog), st)
    assert set(h['long_targets']) == set(s.bosses) and h['long_target_aggregation'] == 'max'
    st.update(visibleBoss=s.bosses[1], remainingBosses=[s.bosses[1]])
    h = scoring_horizon(s.catalog, coverage(s.catalog), st)
    assert h['long_targets'] == {s.bosses[1]: 1} and h['long_target_aggregation'] == 'mean'
    del st['remainingBosses']
    assert scoring_horizon(s.catalog, coverage(s.catalog), st) == h


@pytest.mark.parametrize('bad', [[], None, 'BOSS', ['VANTOM_BOSS']*2, [False], ['MISSING']])
def test_invalid_remaining_bosses_fail(bad):
    s = SwitchingBossScorer()
    with pytest.raises(ValueError):
        scoring_horizon(s.catalog, coverage(s.catalog), dict(state(s), remainingBosses=bad))


def test_uncovered_second_boss_is_not_ignored():
    s = SwitchingBossScorer()
    with pytest.raises(ValueError, match='Uncovered target'):
        scoring_horizon(s.catalog, coverage(s.catalog)-{f'OVERGROWTH:{s.bosses[1]}'}, state(s))


def test_max_per_root_and_leaf_keeps_short_mean_and_changes_ranking(request_data):
    s = SwitchingBossScorer()
    req = dict(request_data, rollout_depth=0, long_targets=dict.fromkeys(s.bosses, 1),
               long_target_aggregation='max', next_floors=[{'targets': dict.fromkeys(s.bosses, 1)}])
    config = dict(short_weight=0, long_weight=1, weak_short_weight=0, weak_long_weight=1,
                  pool_card_ids=['FOOTWORK', 'BACKFLIP'], samples_per_parent=2, keep_per_parent=2, lookahead_pairs=0)
    selector = RewardSelector(s, config)
    result = selector.select(req)
    rows = result['candidates']
    assert [r['initial_long_hp_loss'] for r in rows] == [30, 25, 40, 40]
    assert [r['short_expected_hp_loss'] for r in rows] == [17.5, 25, 25, 25]
    assert result['recommended_card']['id'] == 'BACKFLIP'
    # A weighted mean would wrongly prefer Footwork (17.5 rather than 25).
    assert selector.select(dict(req, long_target_aggregation='mean'))['recommended_card']['id'] == 'FOOTWORK'
    req.update(rollout_depth=2, next_floors=[])
    result = selector.select(req)
    for candidate in result['candidates']:
        for leaf in candidate['leaves']:
            build = deepcopy(req['build'])
            if candidate['card']:
                build['cards'].append(candidate['card'])
            build['cards'].extend(card for card in leaf['path'] if card)
            assert leaf['target_hp_loss'] == max(s.value(build, t) for t in s.bosses)


def test_bot_and_panel_propagate_max_and_short_next_boss(request_data):
    s = SwitchingBossScorer()
    observation = card_observation(request_data)
    observation['state'].update(state(s))
    observation['state']['floorsToBoss'] = 1
    observation['state']['map'] = [dict(row=1, col=0, type='RestSite', children=[dict(row=2,col=0)]),
        dict(row=2,col=0,type='Boss',children=[])]
    bot = BotPolicy(s, config=dict(samples_per_parent=1, keep_per_parent=1, lookahead_pairs=0))
    result = bot.search_card_builds(observation['state'], bot.model.project(bot.raw_build(observation['state'])), [], fixed_depth=0)
    assert result['long_target_aggregation'] == 'max'
    assert result['candidates'][-1]['initial_long_hp_loss'] == 40
    p = payload(request_data)
    p.update(scoring_state=dict(state(s), hp=70), boss_targets={s.bosses[0]: 1}, floors_to_boss=0,
             future_room_types=[{'Boss': 1}])
    result = evaluate(p, RewardSelector(s))
    assert result['scoring_horizon'] == bot.last_report['scoring_horizon']
    assert result['long_target_aggregation'] == 'max'
    assert result['candidates'][-1]['initial_long_hp_loss'] == 40
    assert result['candidates'][-1]['short_details'][0]['targets'] == {s.bosses[0]: 1}
    assert '取掉血较多者' in result['scenario_note']
