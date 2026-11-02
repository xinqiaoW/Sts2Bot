"""Search semantics with a deterministic scorer; no checkpoint required."""
from copy import deepcopy
from collections import Counter
import random
from types import SimpleNamespace

import pytest

from damage_model.schema import Build, Card, Relic
from train.data import load_catalog
from train.reward_policy import RewardSelector, load_config, sample_card_ids, aggregate_leaf_losses


class FakeScorer:
    def __init__(self):
        self.catalog = load_catalog()
        self.predictor = SimpleNamespace(
            vocab=SimpleNamespace(symbol_index={f'card:{cid}': i for i, cid in enumerate(self.catalog.cards)}),
            trained_targets={'OVERGROWTH:FLYCONID_NORMAL', 'OVERGROWTH:BYGONE_EFFIGY_ELITE', 'OVERGROWTH:VANTOM_BOSS'})

    def score_many(self, requests, strict=False):
        output = []
        for r in requests:
            b = Build.from_dict(r['build'])
            self.catalog.validate(b)
            strength = sum({'FOOTWORK': 4, 'BACKFLIP': 2, 'DASH': 3}.get(c.id, 0) for c in b.cards)
            values = {'FLYCONID_NORMAL': 10, 'BYGONE_EFFIGY_ELITE': 20, 'VANTOM_BOSS': 30}
            loss = sum(w * (values[t]-strength) for t, w in r['targets'].items()) / sum(r['targets'].values())
            output.append(dict(expected_hp_loss=loss, untrained_features=[], warnings=[]))
        return output


@pytest.fixture
def request_data():
    catalog = load_catalog()
    neow = next(r for r in catalog.ancients['NEOW']['possible_relics'] if r in catalog.relic_pool
                and r != 'NEOWS_BONES' and not catalog.relics[r]['state_properties'])
    build = Build('OVERGROWTH', 1, tuple(Card(c) for c in catalog.raw['character']['starting_deck']),
                  (Relic('RING_OF_THE_SNAKE'), Relic(neow)), ((1, 'NEOW', neow),), 'reward-test')
    catalog.validate(build)
    return dict(build=build.to_dict(), max_hp=70, floors_to_boss=8,
                rewards=[{'id': c} for c in ['FOOTWORK', 'BACKFLIP', 'DAGGER_THROW']],
                next_floors=[{'targets': {'FLYCONID_NORMAL': 1}},
                             {'targets': {'BYGONE_EFFIGY_ELITE': 1}, 'combat_probability': 0.5}],
                boss_targets={'VANTOM_BOSS': 1})


def selector(**overrides):
    config = dict(samples_per_parent=4, keep_per_parent=4,
                  pool_card_ids=['FOOTWORK', 'BACKFLIP', 'DAGGER_THROW', 'DASH'])
    config.update(overrides)
    return RewardSelector(FakeScorer(), config)


@pytest.mark.parametrize('depth', range(7))
def test_each_parent_branches_not_global_beam(request_data, depth):
    request_data['rollout_depth'] = depth
    result = selector().select(request_data)
    assert [r['leaf_count'] for r in result['candidates']] == [4**depth]*4
    assert all(len(leaf['path']) == depth for r in result['candidates'] for leaf in r['leaves'])
    assert [s['leaves_per_root'] for s in result['stats']['per_depth']] == [[4**i]*4 for i in range(1, depth+1)]
    if depth >= 2:
        assert result['stats']['cache_hits'] > 0
        leaves = result['candidates'][0]['leaves']
        assert len({r['build_id'] for r in leaves}) < len(leaves)


def test_empty_offers_roll_out_current_build_only(request_data):
    request_data.update(options=[], rollout_depth=1)
    result = selector().select(request_data)
    assert result['recommended_action'] == 'skip'
    assert result['score_margin'] == 0
    assert len(result['candidates']) == 1
    assert result['candidates'][0]['leaf_count'] == 4
    assert result['stats']['per_depth'][0]['leaves_per_root'] == [4]


def test_zero_depth_short_probabilities_and_combination(request_data):
    request_data['rollout_depth'] = 0
    result = selector(short_weight=3, long_weight=1, weak_short_weight=3, weak_long_weight=1).select(request_data)
    skip = result['candidates'][3]
    assert skip['short_expected_hp_loss'] == pytest.approx(20 / 1.5)
    assert skip['long_expected_hp_loss'] == 30
    assert skip['combined_score'] == pytest.approx(-17.5)
    assert result['recommended_card']['id'] == 'FOOTWORK'
    assert skip['selected_leaf_count'] == 1
    assert skip['leaves'][0]['aggregation_weight'] == 1


@pytest.mark.parametrize('probability', [1, .25])
def test_short_mean_counts_battles_not_noncombat_rooms(request_data, probability):
    request_data.update(rollout_depth=0, next_floors=[{'combat_probability': 0},
        {'targets': {'FLYCONID_NORMAL': 1, 'BYGONE_EFFIGY_ELITE': 1, 'VANTOM_BOSS': 1},
         'combat_probability': probability}])
    skip = selector().select(request_data)['candidates'][-1]
    assert skip['short_expected_hp_loss'] == pytest.approx((10+20+30)/3)
    assert skip['short_combat_weight'] == probability


def test_top_fraction_k_and_rank_weighting(request_data):
    request_data['rollout_depth'] = 2
    result = selector(leaf_top_fraction=0.5, leaf_top_k=3, leaf_rank_power=1, leaf_bottom_weight=0).select(request_data)
    for option in result['candidates']:
        assert option['selected_leaf_count'] == 3
        leaves = option['leaves']
        assert [l['aggregation_weight'] for l in leaves[:3]] == pytest.approx([6/11, 3/11, 2/11])
        assert all(l['aggregation_weight'] == 0 for l in leaves[3:])
        assert option['long_expected_hp_loss'] == pytest.approx(sum(l['boss_hp_loss']*l['aggregation_weight'] for l in leaves))


def test_best_and_worst_quarters_are_mixed():
    losses = [1, 3, 4, 5, 6, 8, 10, 30]
    result = aggregate_leaf_losses(losses, load_config(None))
    assert result['top_expected_hp_loss'] == pytest.approx(5/3)
    assert result['bottom_expected_hp_loss'] == pytest.approx(70/3)
    assert result['long_expected_hp_loss'] == pytest.approx(12.5)
    assert result['weights'] == pytest.approx([1/3, 1/6, 0, 0, 0, 0, 1/6, 1/3])
    assert result['selected_leaf_count'] == 4


@pytest.mark.parametrize('top,bottom,expected', [(1, 0, 2), (0, 1, 20), (3, 1, 6.5)])
def test_tail_weights_normalized_and_uniform_group_means(top, bottom, expected):
    r = aggregate_leaf_losses([1, 3, 4, 5, 6, 8, 10, 30], load_config(None,
        leaf_top_weight=top, leaf_bottom_weight=bottom, leaf_rank_power=0))
    assert r['long_expected_hp_loss'] == pytest.approx(expected)
    assert sum(r['weights']) == pytest.approx(1)


@pytest.mark.parametrize('losses', [[7], [2, 4, 8]])
def test_overlapping_small_frontier_tails_still_normalize(losses):
    r = aggregate_leaf_losses(losses, load_config(None, leaf_top_fraction=.75, leaf_bottom_fraction=.75))
    assert sum(r['weights']) == pytest.approx(1)
    assert r['selected_leaf_count'] == len(losses)
    assert r['long_expected_hp_loss'] == pytest.approx(sum(w*l for w,l in zip(r['weights'], losses)))


def test_selector_exposes_tail_losses_and_all_leaf_contributions(request_data):
    request_data['rollout_depth'] = 2
    r = selector().select(request_data)
    for candidate in r['candidates']:
        assert candidate['top_leaf_count'] == candidate['bottom_leaf_count'] == 4
        assert candidate['selected_leaf_count'] == 8
        assert candidate['long_expected_hp_loss'] == pytest.approx(
            .5*candidate['top_expected_hp_loss'] + .5*candidate['bottom_expected_hp_loss'])
        assert sum(l['aggregation_weight'] for l in candidate['leaves']) == pytest.approx(1)
        assert candidate['long_expected_hp_loss'] == pytest.approx(
            sum(l['aggregation_weight']*l['boss_hp_loss'] for l in candidate['leaves']))


@pytest.mark.parametrize('override', [dict(leaf_bottom_fraction=0), dict(leaf_bottom_fraction=1.1),
    dict(leaf_top_weight=0, leaf_bottom_weight=0), dict(leaf_bottom_weight=-1),
    dict(leaf_bottom_weight=True), dict(leaf_bottom_weight=float('nan'))])
def test_invalid_tail_config(override):
    with pytest.raises(ValueError):
        load_config(None, **override)


def test_reproducibility_and_reward_order(request_data):
    s = selector()
    original = deepcopy(request_data)
    a, b = s.select(request_data), s.select(request_data)
    assert a['candidates'] == b['candidates']
    assert request_data == original
    request_data['rewards'].reverse()
    reversed_result = s.select(request_data)
    assert [r['combined_score'] for r in a['candidates'][:3]] == list(reversed([r['combined_score'] for r in reversed_result['candidates'][:3]]))


def test_noncombat_floor_and_depth_schedule(request_data):
    s = selector()
    assert [s.depth_for(f) for f in [0, 2, 3, 5, 6, 8, 9, 11, 12, 20]] == [0, 0, 1, 1, 2, 2, 3, 3, 4, 4]
    request_data.update(rollout_depth=0, next_floors=[{'combat_probability': 0}])
    assert s.select(request_data)['candidates'][0]['short_score'] == 0


@pytest.mark.parametrize('override', [dict(leaf_top_fraction=0), dict(samples_per_parent=2),
                                    dict(short_weight=0, long_weight=0), dict(unknown=1),
                                    dict(upgrade_probability=2), dict(leaf_top_k=-1)])
def test_invalid_config(override):
    with pytest.raises(ValueError):
        load_config(None, **override)


@pytest.mark.parametrize('override', [dict(rollout_depth=7), dict(floors_to_boss=-1), dict(current_hp=20),
                                    dict(boss_targets={'FLYCONID_NORMAL': 1}), dict(max_hp=0),
                                    dict(boss_targets={'UNKNOWN_BOSS': 1}), dict(rewards=[])])
def test_invalid_request(request_data, override):
    request_data.update(override)
    with pytest.raises(ValueError):
        selector().select(request_data)


def test_rarity_probabilities_independent_of_pool_size():
    # Deliberately unequal pools: per-card weighting would fail this test.
    cards = {f'{rarity}-{i}': {'rarity': rarity} for rarity, size in
             [('Rare', 2), ('Uncommon', 15), ('Common', 3)] for i in range(size)}
    weights = load_config()['rarity_weights']
    samples = sample_card_ids(sorted(cards), cards, weights, 100_000, random.Random(20261101))
    counts = Counter(cards[c]['rarity'] for c in samples)
    for rarity, weight in weights.items():
        assert counts[rarity] / len(samples) == pytest.approx(weight / 15, abs=0.005)
    card_counts = Counter(samples)
    for rarity in weights:
        group = [cid for cid in cards if cards[cid]['rarity'] == rarity]
        for cid in group:
            assert card_counts[cid] / counts[rarity] == pytest.approx(1/len(group), abs=0.02)


def test_sampling_replacement_missing_categories_and_seed():
    cards = {'gold': {'rarity': 'Rare'}, 'white': {'rarity': 'Common'}}
    weights = {'Rare': 1, 'Uncommon': 5, 'Common': 9}
    a = sample_card_ids(list(cards), cards, weights, 10000, random.Random(123))
    assert a == sample_card_ids(list(cards), cards, weights, 10000, random.Random(123))
    assert a.count('gold') / len(a) == pytest.approx(0.1, abs=0.015)
    assert sample_card_ids(['white'], cards, weights, 32, random.Random(1)) == ['white']*32
    with pytest.raises(ValueError):
        sample_card_ids([], cards, weights, 32, random.Random(1))


@pytest.mark.parametrize('pairs', [0, 1, 2, 3])
def test_two_step_retains_delayed_synergy_without_extra_cards(request_data, monkeypatch, pairs):
    class SynergyScorer(FakeScorer):
        def score_many(self, requests, strict=False):
            rows = super().score_many(requests, strict)
            for request, row in zip(requests, rows):
                counts = Counter(c['id'] for c in request['build']['cards'])
                # Both setup cards are individually bad, together excellent.
                paired = counts['ACCURACY'] and counts['BLADE_DANCE']
                row['expected_hp_loss'] = 5 if paired else (
                    30 + counts['ACCURACY'] + counts['BLADE_DANCE'] - counts['BACKFLIP'])
            return rows

    monkeypatch.setattr('train.reward_policy.sample_card_ids',
                        lambda *args: ['ACCURACY', 'BLADE_DANCE', 'BACKFLIP'])
    s = RewardSelector(SynergyScorer(), dict(samples_per_parent=3, keep_per_parent=1,
        lookahead_pairs=pairs, pool_card_ids=['ACCURACY', 'BLADE_DANCE', 'BACKFLIP']))
    request_data.update(options=[], rollout_depth=2)
    r = s.select(request_data)
    leaf = r['candidates'][0]['leaves'][0]
    assert len(leaf['path']) == 2
    assert leaf['boss_hp_loss'] == (5 if pairs else 28)
    if pairs:
        assert {c['id'] for c in leaf['path']} == {'ACCURACY', 'BLADE_DANCE'}
    request_data['rollout_depth'] = 1
    one = s.select(request_data)['candidates'][0]['leaves'][0]
    assert len(one['path']) == 1
    assert one['boss_hp_loss'] == 29  # No combination beyond the horizon.


@pytest.mark.parametrize('pairs', [0, 2, 3])
def test_multiple_pairs_preserve_branch_counts(request_data, pairs):
    request_data['rollout_depth'] = 5
    result = selector(samples_per_parent=2, keep_per_parent=2, lookahead_pairs=pairs).select(request_data)
    assert [s['leaves_per_root'] for s in result['stats']['per_depth']] == [[2**i]*4 for i in range(1, 6)]
    assert all(len(leaf['path']) == 5 for c in result['candidates'] for leaf in c['leaves'])


@pytest.mark.parametrize('value', [-1, 4, 1.5, True])
def test_invalid_lookahead(value):
    with pytest.raises(ValueError, match='lookahead_pairs'):
        load_config(None, lookahead_pairs=value)


def test_arbitrary_shop_options_and_exact_instance_operations(request_data):
    request_data.pop('rewards')
    request_data['rollout_depth'] = 1
    request_data['options'] = [dict(action='take', card={'id': 'FOOTWORK'})] * 7
    r = selector().select(request_data)
    assert len(r['candidates']) == 8
    assert all(c['leaf_count'] == 4 for c in r['candidates'])
    before = deepcopy(request_data['build'])
    first = before['cards'][0]
    request_data.update(rollout_depth=0, options=[
        dict(action='remove', deck_index=0),
        dict(action='upgrade', deck_index=0, card=dict(first, upgrade=1)),
    ])
    r = selector().select(request_data)
    assert [c['action'] for c in r['candidates']] == ['remove', 'upgrade', 'skip']
    assert request_data['build'] == before
    request_data['options'][1]['card']['id'] = 'FOOTWORK'
    with pytest.raises(ValueError, match='identity'):
        selector().select(request_data)
