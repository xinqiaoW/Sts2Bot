from copy import deepcopy

import pytest

from runctl.policy import BotPolicy
from runctl.policy_config import load_policy_config
from train.scoring_horizon import scoring_horizon, survival_budget
from train.reward_policy import RewardSelector, load_config
from train.advisor_service import evaluate
from test_reward_policy import request_data
from test_bot_policy import card_observation
from test_advisor_service import payload
from test_scoring_horizon import PoolScorer, coverage


def weighted(values):
    return lambda targets: sum(w*values[t] for t,w in targets.items())/sum(targets.values())


def test_short_budget_is_total_not_mean_or_scoring_floor_weights():
    result = survival_budget(70, [dict(targets={'normal':1}),
        dict(targets={'normal':1}, combat_probability=.25)], {'boss':1}, weighted(dict(normal=12,boss=40)))
    assert result['short_total_expected_hp_loss'] == 15
    assert result['remaining_hp'] == 15
    assert result['sufficient']


@pytest.mark.parametrize('hp,sufficient', [(50.1,True), (50,False), (49.9,False)])
def test_zero_boundary_and_deduplicate_boss(hp,sufficient):
    result = survival_budget(hp, [dict(targets={'normal':1}), dict(targets={'boss':1})],
        {'boss':1}, weighted(dict(normal=10,boss=40)))
    assert result['short_total_expected_hp_loss'] == 50
    assert result['short_target_overlap_expected_hp_loss'] == 40
    assert result['short_before_target_expected_hp_loss'] == 10
    assert result['sufficient'] is sufficient


def test_two_elites_count_two_fights_not_one_or_three():
    result = survival_budget(60, [dict(targets={'elite':1}),dict(targets={'elite':1})],
        {'elite':1}, weighted(dict(elite=25)))
    assert result['remaining_hp'] == 10
    assert result['short_target_overlap_expected_hp_loss'] == 25


def test_mixed_branch_and_unknown_room_probabilities():
    result = survival_budget(70, [dict(targets={'elite':1, 'normal':3}, combat_probability=.5),
        dict(targets={}, combat_probability=0)], {'elite':1}, weighted(dict(elite=24,normal=8)))
    assert result['short_total_expected_hp_loss'] == 6
    assert result['short_target_overlap_expected_hp_loss'] == 3
    assert result['remaining_hp'] == 43


def test_consecutive_bosses_sum_for_budget_and_no_double_count():
    result = survival_budget(60, [dict(targets={'bossA':1}),dict(targets={'bossB':1})],
        {'bossA':1,'bossB':1}, weighted(dict(bossA=40,bossB=25)), sequential=True)
    assert result['target_expected_hp_loss'] == 65
    assert result['short_before_target_expected_hp_loss'] == 0
    assert result['remaining_hp'] == -5 and not result['sufficient']


@pytest.mark.parametrize('hp,floor,margin,room', [(60,1,0,'Boss'), (35,1,0,'Elite'),
    (35.1,1,0,'Boss'), (40,1,5,'Elite'), (30,7,0,'Boss')])
def test_elite_target_uses_budget_and_retains_act_floor_rule(hp,floor,margin,room):
    s = PoolScorer()
    def predict(act_id, targets):
        types = {e['id']: e['room_type'] for e in s.catalog.acts[act_id]['encounters']}
        return dict(expected_hp_loss=sum(w*{'Monster':10,'Elite':25,'Boss':40}[types[t]]
            for t,w in targets.items())/sum(targets.values()))
    st = dict(actId='OVERGROWTH', act=1, hp=hp, maxHp=70, actFloor=floor,
              normalCombatsCompleted=3, visibleBoss='VANTOM_BOSS')
    result = scoring_horizon(s.catalog, coverage(s.catalog), st, score_elites=predict,
        elite_safety_margin=margin, short_floors=[dict(targets={'FLYCONID_NORMAL':1})])
    assert result['long_target_room'] == room
    if floor <=6:
        assert result['elite_survival_budget']['remaining_hp'] == pytest.approx(hp-35)
    else:
        assert result['elite_survival_budget'] is None


@pytest.mark.parametrize('hp,margin,mode', [(60,0,'sufficient'), (51,0,'insufficient'),
    (52,1,'insufficient')])
def test_selector_budget_counts_total_and_all_roots_share_weights(request_data,hp,margin,mode):
    s = PoolScorer()
    request_data.update(budget_hp=hp, rollout_depth=1,
        next_floors=[dict(targets={'FLYCONID_NORMAL':1}),dict(targets={'FLYCONID_NORMAL':1})])
    original = deepcopy(request_data)
    result = RewardSelector(s, dict(boss_safety_margin=margin, short_floor_weights=[10,1],
        samples_per_parent=1, keep_per_parent=1, lookahead_pairs=0)).select(request_data)
    weighting = result['score_weighting']
    assert weighting['basis'] == 'survival_budget' and weighting['mode'] == mode
    assert weighting['survival_budget']['short_before_target_expected_hp_loss'] == 16
    assert weighting['survival_budget']['target_expected_hp_loss'] == 35
    expected = (.72,.28) if mode=='insufficient' else (.28,.72)
    for candidate in result['candidates']:
        assert candidate['combined_score'] == pytest.approx(-expected[0]*candidate['short_expected_hp_loss']
            -expected[1]*candidate['long_expected_hp_loss'])
    assert all('budget_hp' not in r and 'current_hp' not in r and 'hp' not in r for r in s.requests)
    assert request_data == original


def test_selected_elite_budget_weights_do_not_use_boss_loss(request_data):
    s=PoolScorer(elite_loss=25)
    request_data.update(budget_hp=25, rollout_depth=0, next_floors=[],
        long_targets={'BYGONE_EFFIGY_ELITE':1}, long_target_room='Elite')
    result=RewardSelector(s).select(request_data)
    assert result['score_weighting']['survival_budget']['target_expected_hp_loss']==25
    assert result['score_weighting']['mode']=='insufficient'


def test_double_boss_ranking_max_but_survival_sums(request_data):
    s=PoolScorer()
    bosses={e['id']:1 for e in s.catalog.acts['OVERGROWTH']['encounters'] if e['room_type']=='Boss'}
    bosses=dict(list(bosses.items())[:2])
    request_data.update(budget_hp=70, rollout_depth=0, next_floors=[],long_targets=bosses,long_target_aggregation='max')
    result=RewardSelector(s).select(request_data)
    assert result['candidates'][-1]['long_expected_hp_loss']==35
    assert result['score_weighting']['survival_budget']['target_expected_hp_loss']==70
    assert result['score_weighting']['mode']=='insufficient'


@pytest.mark.parametrize('hp,mode,target',[(70,'sufficient','Boss'),(30,'insufficient','Elite')])
def test_bot_panel_use_same_hp_and_budget(request_data,hp,mode,target):
    obs=card_observation(request_data)
    obs['state'].update(hp=hp,actFloor=1,normalCombatsCompleted=0)
    bot=BotPolicy(PoolScorer(),config=dict(samples_per_parent=1,keep_per_parent=1,lookahead_pairs=0))
    bot.choose(obs)
    p=payload(request_data)
    p['scoring_state']=dict(hp=hp,actFloor=1,normalCombatsCompleted=0,visibleBoss='VANTOM_BOSS')
    result=evaluate(p,RewardSelector(PoolScorer(),dict(samples_per_parent=1,keep_per_parent=1,lookahead_pairs=0)))
    assert result['scoring_horizon']==bot.last_report['scoring_horizon']
    assert result['score_weighting']==bot.last_report['score_weighting']
    assert result['score_weighting']['mode']==mode
    assert result['long_target_room']==target


@pytest.mark.parametrize('key',['elite_safety_margin','boss_safety_margin'])
@pytest.mark.parametrize('bad',[-1,True,float('inf'),float('nan')])
def test_invalid_margin_config(key,bad):
    for loader in (load_config,load_policy_config):
        with pytest.raises(ValueError): loader(None,**{key:bad})


@pytest.mark.parametrize('bad',[-1,True,71,None,float('nan')])
def test_invalid_budget_hp(request_data,bad):
    with pytest.raises(ValueError): RewardSelector(PoolScorer()).select(dict(request_data,budget_hp=bad,rollout_depth=0))


def test_old_request_explicitly_reports_legacy_weighting(request_data):
    result=RewardSelector(PoolScorer()).select(dict(request_data,rollout_depth=0))
    assert result['score_weighting']['basis']=='legacy_short_loss_threshold'
    assert result['score_weighting']['survival_budget'] is None


def test_weighting_uses_unchanged_deck_not_winning_rollout(request_data):
    from test_adaptive_score_weights import TradeoffScorer
    request_data.update(budget_hp=25, rollout_depth=1, next_floors=[])
    result=RewardSelector(TradeoffScorer(8),dict(pool_card_ids=['FOOTWORK'],samples_per_parent=1,
        keep_per_parent=1,lookahead_pairs=0)).select(request_data)
    assert result['candidates'][-1]['long_expected_hp_loss']==10
    assert result['score_weighting']['survival_budget']['target_expected_hp_loss']==30
    assert result['score_weighting']['mode']=='insufficient'
    assert result['score_weighting']['short_weight']==.72
