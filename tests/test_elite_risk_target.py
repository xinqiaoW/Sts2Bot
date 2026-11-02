import pytest

from runctl.policy import BotPolicy
from runctl.policy_config import load_policy_config
from train.reward_policy import load_config, RewardSelector
from train.advisor_service import evaluate
from train.data import load_catalog
from train.scoring_horizon import scoring_horizon
from test_scoring_horizon import coverage, PoolScorer
from test_reward_policy import request_data
from test_bot_policy import card_observation
from test_advisor_service import payload


@pytest.mark.parametrize('act_id', ['OVERGROWTH', 'UNDERDOCKS', 'HIVE', 'GLORY'])
@pytest.mark.parametrize('act_floor,loss,room', [(1, 19.9, 'Boss'), (1, 20, 'Boss'),
    (1, 20.01, 'Elite'), (6, 60, 'Elite'), (7, 60, 'Boss')])
def test_threshold_floor_boundaries_in_every_act(act_id, act_floor, loss, room):
    catalog = load_catalog()
    act = catalog.acts[act_id]['act']
    boss = next(e['id'] for e in catalog.acts[act_id]['encounters'] if e['room_type'] == 'Boss')
    calls = []
    def probe(aid, targets):
        calls.append((aid, targets))
        return dict(expected_hp_loss=loss)
    state = dict(actId=act_id, act=act, actFloor=act_floor, floor=99,
                 normalCombatsCompleted=4, visibleBoss=boss)
    result = scoring_horizon(catalog, coverage(catalog), state, score_elites=probe)
    assert result['long_target_room'] == room
    assert len(calls) == (0 if act_floor > 6 else 1)
    assert result['estimated_elite_loss'] == (None if act_floor > 6 else loss)
    if act_floor > 6:
        assert result['target_reason'] == 'after_act_floor_limit'


@pytest.mark.parametrize('act_id,next_id,act', [('OVERGROWTH', 'HIVE', 1), ('HIVE', 'GLORY', 2)])
def test_post_boss_easy_elites_use_next_public_boss_pool(act_id, next_id, act):
    c = load_catalog()
    seen = []
    def probe(aid, targets):
        seen.append(aid)
        return dict(expected_hp_loss=20)
    result = scoring_horizon(c, coverage(c), dict(actId=act_id, act=act, actFloor=18,
        actBossDefeated=True, normalCombatsCompleted=9, visibleBoss='OLD_BOSS_MUST_NOT_BE_USED'), score_elites=probe)
    assert result['mode'] == 'next_act_boss' and result['projects_next_act']
    assert result['evaluated_act_floor'] == 0
    assert seen == [next_id]
    assert set(result['long_targets']) == {e['id'] for e in c.acts[next_id]['encounters'] if e['room_type'] == 'Boss'}
    assert sum(result['long_targets'].values()) == pytest.approx(1)


def test_single_unchanged_deck_probe_and_bot_service_configuration_agree(request_data):
    observation = card_observation(request_data)
    observation['state'].update(actFloor=5, normalCombatsCompleted=0)
    scorer = PoolScorer(elite_loss=25)
    config = dict(elite_target_loss_threshold=25, boss_target_after_act_floor=5,
                  samples_per_parent=1, keep_per_parent=1, lookahead_pairs=0)
    bot = BotPolicy(scorer, config=config)
    bot.choose(observation)
    horizon = bot.last_report['scoring_horizon']
    assert horizon['long_target_room'] == 'Boss'  # Equality uses Boss.
    assert len(scorer.requests[0]['build']['cards']) == len(request_data['build']['cards'])
    elite_requests = [r for r in scorer.requests if all(t.endswith('_ELITE') for t in r['targets'])]
    assert len(elite_requests) == 1  # No candidate-specific probe or rollout probe.
    p = payload(request_data)
    p['scoring_state'] = dict(actFloor=5, normalCombatsCompleted=0, visibleBoss='VANTOM_BOSS')
    service = evaluate(p, RewardSelector(PoolScorer(elite_loss=25), config))
    assert service['scoring_horizon'] == horizon


@pytest.mark.parametrize('overrides', [dict(elite_target_loss_threshold=-1), dict(elite_target_loss_threshold=True),
    dict(elite_target_loss_threshold=float('nan')), dict(boss_target_after_act_floor=-1),
    dict(boss_target_after_act_floor=6.5), dict(boss_target_after_act_floor=True)])
def test_invalid_gate_configuration(overrides):
    for loader in (load_config, load_policy_config):
        with pytest.raises(ValueError):
            loader(None, **overrides)


@pytest.mark.parametrize('loss', [float('nan'), float('inf'), -1, True])
def test_invalid_elite_prediction_is_not_silently_treated_as_easy(loss):
    c = load_catalog()
    with pytest.raises(ValueError, match='Elite expected loss'):
        scoring_horizon(c, coverage(c), dict(actId='OVERGROWTH', act=1, actFloor=1,
            normalCombatsCompleted=3, visibleBoss='VANTOM_BOSS'),
            score_elites=lambda *args: dict(expected_hp_loss=loss))


def test_missing_floor_reports_legacy_fallback_without_using_global_floor():
    c = load_catalog()
    result = scoring_horizon(c, coverage(c), dict(actId='HIVE', act=2, floor=25,
        normalCombatsCompleted=4,
        visibleBoss=next(e['id'] for e in c.acts['HIVE']['encounters'] if e['room_type'] == 'Boss')))
    assert result['target_reason'] == 'missing_act_floor'
    assert result['estimated_elite_loss'] is None
    assert 'missing_act_floor_for_target_switch:using_boss' in result['warnings']
