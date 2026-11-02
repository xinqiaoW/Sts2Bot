from copy import deepcopy
from dataclasses import replace

import pytest

from damage_model.schema import Build, Card
from runctl.policy import BotPolicy
from runctl.policy_config import load_policy_config
from train.reward_policy import RewardSelector, load_config
from test_reward_policy import FakeScorer, request_data


class UpgradeScorer(FakeScorer):
    def score_many(self, requests, strict=False):
        result = []
        for request in requests:
            build = Build.from_dict(request['build'])
            self.catalog.validate(build)
            loss = (5 if any(c.id=='FOOTWORK' and c.upgrade for c in build.cards)
                    else 35 if any(c.id=='FOOTWORK' for c in build.cards)
                    else 20 if any(c.id=='BACKFLIP' for c in build.cards) else 30)
            result.append(dict(expected_hp_loss=loss, warnings=[], untrained_features=[]))
        return result


def selector(scorer=None, **config):
    return RewardSelector(scorer or UpgradeScorer(), dict(samples_per_parent=1, keep_per_parent=1,
        lookahead_pairs=0, pool_card_ids=['DAGGER_THROW'], short_weight=0, long_weight=1,
        weak_short_weight=0, weak_long_weight=1, **config))


def test_reward_weak_until_upgraded_is_selected(request_data):
    request_data['rollout_depth'] = 1
    old = selector(rollout_max_upgrades=0).select(request_data)
    new = selector().select(request_data)
    assert old['recommended_card']['id'] == 'BACKFLIP'
    assert new['recommended_card']['id'] == 'FOOTWORK'
    leaf = new['candidates'][0]['leaves'][0]
    assert leaf['path'] == [dict(action='upgrade', deck_index=len(request_data['build']['cards']),
                                card=dict(id='FOOTWORK', upgrade=1))]
    assert leaf['upgrade_count'] == 1
    assert leaf['target_hp_loss'] == 5
    assert new['candidates'][0]['initial_long_hp_loss'] == 35
    assert new['candidates'][0]['short_expected_hp_loss'] == 35  # No premature upgrade credit.


def replay(build, path):
    build = Build.from_dict(build)
    for step in path:
        if step is None:
            continue
        cards = list(build.cards)
        if step.get('action') == 'upgrade':
            index = step['deck_index']
            upgraded = Card(**step['card'])
            assert upgraded == replace(cards[index], upgrade=cards[index].upgrade+1)
            cards[index] = upgraded
        else:
            cards.append(Card(**step))
        build = replace(build, cards=tuple(cards))
    return build


@pytest.mark.parametrize('pairs', [0, 1, 2])
@pytest.mark.parametrize('cap', [0, 1, 2])
def test_bounded_upgrades_preserve_width_depth_and_replay(request_data, pairs, cap):
    request_data.update(options=[], rollout_depth=3)
    original = deepcopy(request_data)
    policy = RewardSelector(UpgradeScorer(), dict(samples_per_parent=3, keep_per_parent=3,
        lookahead_pairs=pairs, rollout_max_upgrades=cap, pool_card_ids=['FOOTWORK','DAGGER_THROW']))
    result = policy.select(request_data)
    assert result['candidates'][0]['leaf_count'] == 3**3
    assert [r['leaves_per_root'] for r in result['stats']['per_depth']] == [[3],[9],[27]]
    for leaf in result['candidates'][0]['leaves']:
        assert len(leaf['path']) == 3
        assert leaf['upgrade_count'] == sum(bool(step and step.get('action')=='upgrade') for step in leaf['path'])
        assert leaf['upgrade_count'] <= cap
        assert replay(request_data['build'],leaf['path']).id == leaf['build_id']
    assert request_data == original
    if not cap:
        assert result['stats']['upgrade_candidates'] == result['stats']['upgrade_branches'] == 0


def test_newly_sampled_card_can_be_upgraded_in_next_depth(request_data):
    request_data.update(options=[], rollout_depth=2)
    policy = RewardSelector(UpgradeScorer(), dict(samples_per_parent=1, keep_per_parent=1,
        lookahead_pairs=1, rollout_max_upgrades=1, pool_card_ids=['FOOTWORK']))
    result = policy.select(request_data)
    leaf = result['candidates'][0]['leaves'][0]
    assert leaf['path'][0] == dict(id='FOOTWORK',upgrade=0)
    assert leaf['path'][1]['action'] == 'upgrade'
    assert leaf['target_hp_loss'] == 5


def test_upgrade_preserves_enchantment_and_exact_owned_instance(request_data):
    request_data.update(options=[], rollout_depth=1)
    request_data['build']['cards'].extend([dict(id='FOOTWORK',upgrade=1),
        dict(id='FOOTWORK',enchantment_id='GLAM',enchantment_amount=1)])
    class LastInstance(UpgradeScorer):
        def score_many(self,requests,strict=False):
            results=super().score_many(requests,strict)
            for r,row in zip(requests,results):
                row['expected_hp_loss']=1 if any(c['id']=='FOOTWORK' and c.get('enchantment_id')=='GLAM'
                    and c.get('upgrade')==1 for c in r['build']['cards']) else 30
            return results
    result=selector(LastInstance()).select(request_data)
    leaf=result['candidates'][0]['leaves'][0]
    step=leaf['path'][0]
    assert step['deck_index']==len(request_data['build']['cards'])-1
    assert step['card']['enchantment_id']=='GLAM' and step['card']['enchantment_amount']==1
    assert replay(request_data['build'],leaf['path']).id==leaf['build_id']


def test_all_upgraded_deck_has_no_fake_upgrade_branch(request_data):
    policy=selector()
    for card in request_data['build']['cards']:
        card['upgrade']=policy.catalog.cards[card['id']]['max_upgrade_level']
    request_data.update(options=[],rollout_depth=1)
    result=policy.select(request_data)
    assert result['stats']['upgrade_branches']==0
    assert result['stats']['upgrade_candidates']==0


def test_depth_zero_has_no_future_upgrade_credit(request_data):
    request_data.update(rollout_depth=0)
    result=selector().select(request_data)
    assert result['recommended_card']['id']=='BACKFLIP'
    assert result['stats']['upgrade_branches']==0
    assert all(not c['leaves'][0]['path'] for c in result['candidates'])


@pytest.mark.parametrize('cap', [-1, 1.5, True, 7])
def test_invalid_caps_rejected(cap):
    with pytest.raises(ValueError):load_config(None,rollout_max_upgrades=cap)
    with pytest.raises(ValueError):load_policy_config(rollout_max_upgrades=cap)


def test_bot_passes_config_to_reward_selector():
    bot=BotPolicy(UpgradeScorer(),config=dict(rollout_max_upgrades=2))
    assert bot.reward_config['rollout_max_upgrades']==2
