from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from damage_model.schema import Build, Relic
from runctl.policy import BotPolicy
from train.data import load_catalog
from train.score import BuildScorer
from train.scoring_horizon import scoring_horizon
from train.reward_policy import RewardSelector
from train.advisor_service import evaluate
from test_reward_policy import FakeScorer, request_data
from test_bot_policy import card_observation
from test_advisor_service import payload


def coverage(catalog):
    return {f'{a}:{e["id"]}' for a, value in catalog.acts.items() for e in value['encounters']}


@pytest.mark.parametrize('act_id,act,limit', [('OVERGROWTH', 1, 3), ('UNDERDOCKS', 1, 3), ('HIVE', 2, 2), ('GLORY', 3, 2)])
def test_early_elite_risk_is_independent_of_weak_pool_count(act_id, act, limit):
    catalog = load_catalog()
    boss = next(e['id'] for e in catalog.acts[act_id]['encounters'] if e['room_type'] == 'Boss')
    state = dict(actId=act_id, act=act, actFloor=6, visibleBoss=boss)
    for count in range(limit+1):
        result = scoring_horizon(catalog, coverage(catalog), dict(state, normalCombatsCompleted=count),
                                 score_elites=lambda *args: dict(expected_hp_loss=21))
        assert result['mode'] == 'elite_risk'
        expected = {e['id'] for e in catalog.acts[act_id]['encounters'] if e['room_type'] == 'Elite'}
        assert set(result['long_targets']) == expected
        if count < limit:
            assert set(result['short_targets']) == {e['id'] for e in catalog.acts[act_id]['encounters']
                if e['room_type'] == 'Monster' and e['weak']}


@pytest.mark.parametrize('act_id,act,next_id', [('OVERGROWTH', 1, 'HIVE'), ('UNDERDOCKS', 1, 'HIVE'), ('HIVE', 2, 'GLORY')])
def test_post_boss_uses_only_next_act_public_pools(act_id, act, next_id):
    c = load_catalog()
    state = dict(actId=act_id, act=act, normalCombatsCompleted=10, actBossDefeated=True,
                 visibleBoss='MUST_NOT_READ_OLD_OR_FUTURE_BOSS')
    result = scoring_horizon(c, coverage(c), state, score_elites=lambda *args: dict(expected_hp_loss=21))
    assert result['mode'] == 'next_act_elite_risk'
    assert result['encounter_act_id'] == next_id
    assert set(result['long_targets']) == {e['id'] for e in c.acts[next_id]['encounters'] if e['room_type'] == 'Elite'}
    assert set(result['short_targets']) == {e['id'] for e in c.acts[next_id]['encounters'] if e['weak']}


def test_second_boss_remains_target_and_terminal_has_no_future():
    c = load_catalog()
    boss = next(e['id'] for e in c.acts['GLORY']['encounters'] if e['room_type'] == 'Boss')
    state = dict(actId='GLORY', act=3, actFloor=18, normalCombatsCompleted=8, visibleBoss=boss, actBossDefeated=False)
    assert scoring_horizon(c, coverage(c), state)['long_targets'] == {boss: 1}
    state['actBossDefeated'] = True
    result = scoring_horizon(c, coverage(c), state)
    assert result['mode'] == 'terminal' and result['long_targets'] == {} and result['short_targets'] == {}


class PoolScorer(FakeScorer):
    def __init__(self, elite_loss=25):
        super().__init__()
        self.predictor.trained_targets = coverage(self.catalog)
        self.requests = []
        self.elite_loss = elite_loss

    def score_many(self, requests, strict=False):
        self.requests.extend(deepcopy(requests))
        result = []
        for request in requests:
            self.catalog.validate(Build.from_dict(request['build']))
            act_id = request.get('encounter_act_id', request['build']['act_id'])
            types = {e['id']: e['room_type'] for e in self.catalog.acts[act_id]['encounters']}
            loss = sum(w*{'Monster': 8, 'Elite': self.elite_loss, 'Boss': 35}[types[t]] for t, w in request['targets'].items()) / sum(request['targets'].values())
            result.append(dict(expected_hp_loss=loss, untrained_features=[], warnings=[]))
        return result


@pytest.mark.parametrize('count,completed,mode', [(0, False, 'elite_risk'), (3, False, 'boss'), (10, True, 'next_act_elite_risk')])
def test_bot_and_service_share_horizon_and_owned_state(request_data, count, completed, mode):
    observation = card_observation(request_data)
    act_floor = 1 if count == 0 else 7
    observation['state'].update(normalCombatsCompleted=count, actBossDefeated=completed, actFloor=act_floor, hp=30)
    original = deepcopy(observation)
    scorer = PoolScorer()
    bot = BotPolicy(scorer, config=dict(samples_per_parent=1, keep_per_parent=1, lookahead_pairs=0))
    bot.choose(observation)
    horizon = bot.last_report['scoring_horizon']
    assert horizon['mode'] == mode
    assert observation == original
    p = payload(request_data)
    p.update(scoring_state=dict(hp=30, normalCombatsCompleted=count, actBossDefeated=completed, actFloor=act_floor, visibleBoss='VANTOM_BOSS'),
             future_room_types=[])
    result = evaluate(p, RewardSelector(PoolScorer(), dict(samples_per_parent=1, keep_per_parent=1, lookahead_pairs=0)))
    assert result['scoring_horizon'] == horizon
    if completed:
        assert result['rollout_depth'] == 3
        assert all(r['build']['act'] == 1 and len(r['build']['ancient_history']) == 1 for r in scorer.requests)
        assert all(r['encounter_act_id'] == 'HIVE' for r in scorer.requests)
        assert not any(t.endswith('_BOSS') for r in scorer.requests for t in r['targets'])
        assert bot.last_report['projected_boss_loss'] is None


def test_cross_act_encoder_preserves_actual_inventory_and_validates_real_history(request_data):
    scorer = BuildScorer.__new__(BuildScorer)
    scorer.catalog = load_catalog()
    captured = []
    def predict(inputs, **kwargs):
        captured.extend(inputs)
        return [dict(expected_hp_loss=12, death_probability=0, untrained_features=[]) for _ in inputs]
    scorer.predictor = SimpleNamespace(predict_many=predict)
    target = next(e['id'] for e in scorer.catalog.acts['HIVE']['encounters'] if e['room_type'] == 'Elite')
    request = dict(build=deepcopy(request_data['build']), max_hp=70, targets={target: 1}, encounter_act_id='HIVE')
    before = deepcopy(request)
    result = scorer.score_many([request])[0]
    projected = captured[0][0]
    original = Build.from_dict(request_data['build'])
    assert projected.act_id == 'HIVE' and projected.act == 2
    assert projected.cards == original.cards and projected.relics == original.relics
    assert projected.ancient_history == original.ancient_history
    assert request == before
    assert 'cross_act_projection_without_future_rewards' in result['warnings']
    request['build']['ancient_history'] = []
    with pytest.raises(ValueError, match='Ancient history'):
        scorer.score_many([request])
    request = dict(before, encounter_act_id='GLORY')
    with pytest.raises(ValueError, match='current or next'):
        scorer.score_many([request])


def test_terminal_selector_scores_zero_without_model_or_rollout(request_data):
    scorer = PoolScorer()
    build = Build.from_dict(request_data['build'])
    for act_id in ('HIVE', 'GLORY'):
        spec = scorer.catalog.acts[act_id]
        owned = {r.id for r in build.relics}
        ancient, relic = next((a, r) for a in spec['ancients']
            for r in scorer.catalog.ancients[a]['possible_relics'] if r in scorer.catalog.relic_pool
            and r not in owned and not scorer.catalog.relics[r]['state_properties'])
        build = replace(build, act_id=act_id, act=spec['act'], relics=build.relics+(Relic(relic),),
                        ancient_history=build.ancient_history+((spec['act'], ancient, relic),))
        scorer.catalog.validate(build)
    request_data.update(build=build.to_dict(), terminal=True, long_targets={}, long_target_room=None,
                        next_floors=[], rollout_depth=5)
    result = RewardSelector(scorer).select(request_data)
    assert result['rollout_depth'] == 0 and result['recommended_action'] == 'skip'
    assert all(c['combined_score'] == 0 for c in result['candidates'])
    assert not scorer.requests


def test_empty_elite_coverage_is_not_replaced_by_boss():
    c = load_catalog()
    with pytest.raises(ValueError, match='No trained Elite'):
        scoring_horizon(c, {t for t in coverage(c) if not t.endswith('_ELITE')}, dict(actId='OVERGROWTH', act=1,
            actFloor=1, normalCombatsCompleted=0, visibleBoss='VANTOM_BOSS'),
            score_elites=lambda *args: dict(expected_hp_loss=30))


def test_cross_act_config_depth_applies_only_without_fixed_reward_override(request_data):
    observation = card_observation(request_data)
    state = observation['state']
    state.update(actBossDefeated=True, normalCombatsCompleted=10, floorsToBoss=0)
    bot = BotPolicy(PoolScorer(), config=dict(post_boss_rollout_depth=2,
        samples_per_parent=1, keep_per_parent=1, lookahead_pairs=0))
    build = bot.model.project(bot.raw_build(state))
    result = bot.search_card_builds(state, build, [], fixed_depth=None)
    assert result['rollout_depth'] == 2
    assert bot.last_report['rollout_depth_mode'] == 'post_boss'
    result = bot.search_card_builds(state, build, [], fixed_depth=3)
    assert result['rollout_depth'] == 3
    assert bot.last_report['rollout_depth_mode'] == 'fixed_reward'


def test_crisis_post_boss_depth_does_not_use_finished_act_distance(request_data):
    state = card_observation(request_data)['state']
    state.update(actBossDefeated=True, normalCombatsCompleted=10, floorsToBoss=0, hp=20)
    bot = BotPolicy(PoolScorer(elite_loss=60), config=dict(post_boss_rollout_depth=2,
        samples_per_parent=1, keep_per_parent=1, lookahead_pairs=0,
        crisis_samples_per_parent=1, crisis_keep_per_parent=1, crisis_extra_depth=1))
    result = bot.search_card_builds(state, bot.model.project(bot.raw_build(state)), [])
    assert bot.last_report['crisis'] is True
    assert bot.last_report['crisis_target_room'] == 'Elite'
    assert bot.last_report['rollout_depth_mode'] == 'post_boss'
    assert result['rollout_depth'] == 3
    assert len(result['stats']['per_depth']) == 3
