from copy import deepcopy

import pytest

from runctl.policy import BotPolicy
from runctl.policy_config import load_policy_config
from test_bot_policy import card_observation
from test_reward_policy import FakeScorer, request_data
from train.reward_policy import RewardSelector, load_config, score_weighting


class TradeoffScorer(FakeScorer):
    def __init__(self, baseline):
        super().__init__()
        self.baseline = baseline

    def score_many(self, requests, strict=False):
        result = []
        for request in requests:
            cards = {c['id'] for c in request['build']['cards']}
            if 'FOOTWORK' in cards:
                short, long = max(0, self.baseline-1), 10
            elif 'BACKFLIP' in cards:
                short, long = max(0, self.baseline-15), 20
            else:
                short, long = self.baseline, 30
            targets = request['targets']
            loss = sum(w*(long if t.endswith('_BOSS') else short) for t, w in targets.items()) / sum(targets.values())
            result.append(dict(expected_hp_loss=loss, untrained_features=[], warnings=[]))
        return result


@pytest.mark.parametrize('baseline,mode,card,weights', [
    (10, 'sufficient', 'FOOTWORK', (.28, .72)),
    (10.001, 'insufficient', 'BACKFLIP', (.72, .28)),
    (20, 'insufficient', 'BACKFLIP', (.72, .28)),
])
def test_threshold_changes_real_ranking_using_one_pair_for_all_roots(request_data, baseline, mode, card, weights):
    request_data.update(rollout_depth=0, next_floors=[{'targets': {'FLYCONID_NORMAL': 1}}])
    selector = RewardSelector(TradeoffScorer(baseline))
    before = deepcopy(selector.config)
    result = selector.select(request_data)
    assert result['recommended_card']['id'] == card
    assert result['score_weighting']['mode'] == mode
    assert result['score_weighting']['baseline_short_expected_hp_loss'] == baseline
    for candidate in result['candidates']:
        assert candidate['combined_score'] == pytest.approx(
            -(weights[0]*candidate['short_expected_hp_loss'] + weights[1]*candidate['long_expected_hp_loss']))
    assert selector.config == before


def test_gate_is_per_battle_even_with_sum_or_noncombat_rooms(request_data):
    request_data.update(rollout_depth=0, next_floors=[{'combat_probability': 0},
        {'targets': {'FLYCONID_NORMAL': 1}, 'combat_probability': .25}])
    selector = RewardSelector(TradeoffScorer(20), dict(short_reduction='sum'))
    result = selector.select(request_data)
    assert result['candidates'][-1]['short_expected_hp_loss'] == 5
    assert result['score_weighting']['baseline_short_expected_hp_loss'] == 20
    assert result['score_weighting']['mode'] == 'insufficient'
    request_data['next_floors'] = []
    result = selector.select(request_data)
    assert result['score_weighting']['mode'] == 'no_short_combat'
    assert result['score_weighting']['baseline_short_expected_hp_loss'] is None


def test_configurable_normalized_weights_and_fixed_pair():
    config = load_config(None, short_weight=2, long_weight=8, weak_short_weight=9, weak_long_weight=1,
                         short_strength_loss_threshold=15)
    assert score_weighting(15, config)['short_weight'] == .2
    assert score_weighting(15.1, config)['short_weight'] == .9
    config.update(weak_short_weight=2, weak_long_weight=8)
    assert score_weighting(100, config)['short_weight'] == .2


@pytest.mark.parametrize('overrides', [dict(short_strength_loss_threshold=-1),
    dict(short_strength_loss_threshold=True), dict(weak_short_weight=float('inf')),
    dict(weak_short_weight=0, weak_long_weight=0), dict(weak_short_weight=1e308, weak_long_weight=1e308)])
def test_both_configuration_loaders_reject_invalid_values(overrides):
    for loader in (load_config, load_policy_config):
        with pytest.raises(ValueError):
            loader(None, **overrides)


def test_bot_forwards_custom_gate_and_reports_final_weights(request_data):
    observation = card_observation(request_data)
    observation['state']['map'] = [
        dict(row=1, col=0, type='Monster', children=[dict(row=2, col=0)]),
        dict(row=2, col=0, type='Monster', children=[])]
    bot = BotPolicy(TradeoffScorer(20), config=dict(short_strength_loss_threshold=15, boss_safety_margin=20,
        weak_short_weight=9, weak_long_weight=1, samples_per_parent=1, keep_per_parent=1,
        max_rollout_depth=0, crisis_boss_loss_threshold=1000))
    bot.choose(observation)
    assert bot.reward_config['boss_safety_margin'] == 20
    assert bot.last_report['score_weighting']['survival_budget']['remaining_hp'] == 20
    assert bot.last_report['score_weighting']['mode'] == 'insufficient'
    assert bot.last_report['score_weighting']['short_weight'] == .9
