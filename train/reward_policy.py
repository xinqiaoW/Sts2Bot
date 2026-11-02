"""Reward selection: near-term loss plus best/worst retained target rollout tails."""
from __future__ import annotations

import argparse
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import random
import time

from damage_model.schema import Build, Card, canonical
from . import ROOT
from .score import BuildScorer, DEFAULT_CHECKPOINT
from .scoring_horizon import survival_budget

DEFAULT_CONFIG = ROOT / 'configs/reward-policy.json'


def positive(value, name, *, zero=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 or (value == 0 and not zero):
        raise ValueError(f'{name} must be finite and {"nonnegative" if zero else "positive"}')


def load_config(path=DEFAULT_CONFIG, **overrides):
    config = json.loads(Path(DEFAULT_CONFIG).read_text())
    supplied = json.loads(Path(path).read_text()) if path else {}
    supplied.update(overrides)
    if supplied.keys() - config.keys():
        raise ValueError(f'Unknown config keys: {supplied.keys() - config.keys()}')
    config.update(supplied)
    for key in ('short_weight', 'long_weight', 'weak_short_weight', 'weak_long_weight',
                'short_strength_loss_threshold', 'elite_target_loss_threshold', 'elite_safety_margin', 'boss_safety_margin',
                'leaf_rank_power', 'leaf_top_weight', 'leaf_bottom_weight'):
        positive(config[key], key, zero=True)
    positive(config['short_weight'] + config['long_weight'], 'total score weight')
    positive(config['weak_short_weight'] + config['weak_long_weight'], 'total weak score weight')
    positive(config['leaf_top_weight'] + config['leaf_bottom_weight'], 'total tail weight')
    for key in ('samples_per_parent', 'keep_per_parent', 'inference_batch_size', 'cpu_threads'):
        if type(config[key]) is not int or config[key] < 1:
            raise ValueError(f'{key} must be a positive integer')
    if config['keep_per_parent'] > config['samples_per_parent'] + 1:
        raise ValueError('keep_per_parent exceeds sampled cards plus skip')
    if type(config['rollout_max_upgrades']) is not int or not 0 <= config['rollout_max_upgrades'] <= 6:
        raise ValueError('rollout_max_upgrades must be an integer in [0,6]')
    if type(config['lookahead_pairs']) is not int or not 0 <= config['lookahead_pairs'] <= 3:
        raise ValueError('lookahead_pairs must be an integer in [0,3]')
    if type(config['post_boss_rollout_depth']) is not int or not 0 <= config['post_boss_rollout_depth'] <= 6:
        raise ValueError('post_boss_rollout_depth must be an integer in [0,6]')
    if type(config['boss_target_after_act_floor']) is not int or config['boss_target_after_act_floor'] < 0:
        raise ValueError('boss_target_after_act_floor must be a nonnegative integer')
    if type(config['seed']) is not int or type(config['strict_features']) is not bool:
        raise ValueError('seed must be integer and strict_features must be boolean')
    if config['short_reduction'] not in ('mean', 'sum'):
        raise ValueError('short_reduction must be mean or sum')
    if not isinstance(config['short_floor_weights'], list) or len(config['short_floor_weights']) != 2:
        raise ValueError('Provide exactly two short_floor_weights')
    for w in config['short_floor_weights']:
        positive(w, 'short_floor_weight')
    positive(config['leaf_top_fraction'], 'leaf_top_fraction')
    positive(config['leaf_bottom_fraction'], 'leaf_bottom_fraction')
    positive(config['upgrade_probability'], 'upgrade_probability', zero=True)
    if config['leaf_top_fraction'] > 1 or config['leaf_bottom_fraction'] > 1 or config['upgrade_probability'] > 1:
        raise ValueError('Fractions/probabilities must be <= 1')
    k = config['leaf_top_k']
    if k is not None and (type(k) is not int or k < 1):
        raise ValueError('leaf_top_k must be null or a positive integer')
    if set(config['rarity_weights']) != {'Common', 'Uncommon', 'Rare'}:
        raise ValueError('rarity_weights requires Common, Uncommon, Rare')
    for w in config['rarity_weights'].values():
        positive(w, 'rarity weight', zero=True)
    positive(sum(config['rarity_weights'].values()), 'rarity weight sum')
    pool = config['pool_card_ids']
    if pool is not None and (not isinstance(pool, list) or not pool or any(not isinstance(c, str) for c in pool) or len(pool) != len(set(pool))):
        raise ValueError('pool_card_ids must be null or a nonempty unique ID list')
    schedule = config['depth_schedule']
    if not isinstance(schedule, list) or not schedule or schedule[-1].get('max_floors_to_boss') is not None:
        raise ValueError('depth_schedule must end with a null upper bound')
    previous, previous_depth = -1, -1
    for i, row in enumerate(schedule):
        if set(row) != {'max_floors_to_boss', 'depth'}:
            raise ValueError('Invalid depth_schedule entry')
        bound, depth = row['max_floors_to_boss'], row['depth']
        if type(depth) is not int or not 0 <= depth <= 4 or depth < previous_depth:
            raise ValueError('Schedule depths must be nondecreasing integers in [0,4]')
        if i < len(schedule)-1:
            if type(bound) is not int or bound <= previous:
                raise ValueError('Schedule bounds must be increasing nonnegative integers')
            previous = bound
        previous_depth = depth
    return config


def score_weighting(baseline_short_mean, config, *, budget=None):
    """One common pair for every candidate, based only on the unchanged deck."""
    if baseline_short_mean is not None and not math.isfinite(baseline_short_mean):
        raise ValueError('Baseline short loss must be finite')
    weak = not budget['sufficient'] if budget is not None else (
        baseline_short_mean is not None and baseline_short_mean > config['short_strength_loss_threshold'])
    prefix = 'weak_' if weak else ''
    short, long = config[prefix + 'short_weight'], config[prefix + 'long_weight']
    total = short + long
    return dict(mode='no_short_combat' if baseline_short_mean is None and budget is None else 'insufficient' if weak else 'sufficient',
                basis='survival_budget' if budget is not None else 'legacy_short_loss_threshold', survival_budget=budget,
                baseline_short_expected_hp_loss=baseline_short_mean,
                short_strength_loss_threshold=config['short_strength_loss_threshold'],
                short_weight=short / total, long_weight=long / total)


@dataclass
class Node:
    build: Build
    path: list
    loss: float = 0.0
    upgrades: int = 0


def aggregate_leaf_losses(ranked_losses, config):
    """Mix best/worst tails of ascending losses, not the unpruned future distribution.

    Existing rank weights are mirrored: the worst leaf has rank 1 within the
    bottom tail. For small frontiers tails may overlap; their contributions add
    to one normalized weight per leaf (including the depth-zero singleton).
    """
    size = len(ranked_losses)
    if not size or any(not math.isfinite(x) for x in ranked_losses):
        raise ValueError('Leaf losses must be nonempty and finite')
    top_count = max(1, math.ceil(size * config['leaf_top_fraction']))
    if config['leaf_top_k'] is not None:
        top_count = min(top_count, config['leaf_top_k'])
    bottom_count = max(1, math.ceil(size * config['leaf_bottom_fraction']))
    total = config['leaf_top_weight'] + config['leaf_bottom_weight']
    weights = [0.0] * size
    tail_losses = []
    for indices, mass in ((range(top_count), config['leaf_top_weight'] / total),
                          (range(size-1, size-bottom_count-1, -1), config['leaf_bottom_weight'] / total)):
        raw = [(rank+1) ** -config['leaf_rank_power'] for rank in range(len(indices))]
        norm = sum(raw)
        tail_loss = 0.0
        for index, weight in zip(indices, raw):
            weight /= norm
            tail_loss += weight * ranked_losses[index]
            weights[index] += mass * weight
        tail_losses.append(tail_loss)
    return dict(top_expected_hp_loss=tail_losses[0], bottom_expected_hp_loss=tail_losses[1],
                top_leaf_count=top_count, bottom_leaf_count=bottom_count,
                selected_leaf_count=sum(w > 0 for w in weights),
                long_expected_hp_loss=sum(w * loss for w, loss in zip(weights, ranked_losses)),
                weights=weights)


def sample_card_ids(pool, cards, rarity_weights, count, rng):
    """Independent draws: rarity first, then uniform card within that rarity.

    Replacement preserves category probabilities even with small card pools.
    Missing or disabled categories are excluded and remaining weights normalized.
    Duplicate draws remain distinct search branches (inference is cached).
    """
    groups = {rarity: [cid for cid in pool if cards[cid]['rarity'] == rarity]
              for rarity in sorted(rarity_weights) if rarity_weights[rarity] > 0}
    rarities = [rarity for rarity, ids in groups.items() if ids]
    if not rarities:
        raise ValueError('No eligible reward cards with positive rarity weight')
    weights = [rarity_weights[rarity] for rarity in rarities]
    return [rng.choice(groups[rng.choices(rarities, weights=weights, k=1)[0]])
            for _ in range(count)]


class RewardSelector:
    def __init__(self, scorer=None, config=None):
        self.config = load_config(None, **(config or {}))
        self.scorer = scorer if scorer is not None else BuildScorer()
        self.catalog = self.scorer.catalog

    def depth_for(self, floors):
        if type(floors) is not int or floors < 0:
            raise ValueError('floors_to_boss must be a nonnegative integer')
        return next(row['depth'] for row in self.config['depth_schedule']
                    if row['max_floors_to_boss'] is None or floors <= row['max_floors_to_boss'])

    def pool(self):
        c = self.config
        eligible = sorted(cid for cid in self.catalog.card_pool
                          if self.catalog.cards[cid]['pool'] == 'SILENT_CARD_POOL'
                          and self.catalog.cards[cid]['rarity'] in c['rarity_weights'])
        if c['pool_card_ids'] is not None:
            if set(c['pool_card_ids']) - set(eligible):
                raise ValueError('pool_card_ids contains cards outside ordinary Silent rewards')
            eligible = sorted(c['pool_card_ids'])
        vocab = self.scorer.predictor.vocab.symbol_index
        return [cid for cid in eligible if c['rarity_weights'][self.catalog.cards[cid]['rarity']] > 0
                and (not c['strict_features'] or f'card:{cid}' in vocab)]

    def select(self, request):
        started = time.perf_counter()
        c = self.config
        if 'current_hp' in request or 'hp' in request:
            raise ValueError('Current HP is unsupported by the full-health model')
        build = Build.from_dict(request['build'])
        self.catalog.validate(build)
        hp = request['max_hp']
        positive(hp, 'max_hp')
        budget_hp = request.get('budget_hp')
        if 'budget_hp' in request:
            positive(budget_hp, 'budget_hp', zero=True)
            if budget_hp > hp:
                raise ValueError('budget_hp must not exceed max_hp')
        depth = self.depth_for(request['floors_to_boss'])
        if 'rollout_depth' in request:
            depth = request['rollout_depth']
            if type(depth) is not int or not 0 <= depth <= 6:
                raise ValueError('rollout_depth must be an integer in [0,6]')
        seed = request.get('seed', c['seed'])
        if type(seed) is not int:
            raise ValueError('seed must be an integer')
        if 'options' in request:
            options = request['options']
            if not isinstance(options, list) or not 0 <= len(options) <= 90:
                raise ValueError('options must contain 0 to 90 explicit card operations')
        else:
            rewards = request['rewards']
            if not isinstance(rewards, list) or len(rewards) != 3:
                raise ValueError('Exactly three reward cards are required')
            options = [dict(action='take', card=card) for card in rewards]
        root_builds, choices = [], []
        for option in options:
            action = option['action']
            deck = list(build.cards)
            if action == 'take':
                card = Card(**option['card'])
                deck.append(card)
            elif action in ('remove', 'upgrade'):
                index = option['deck_index']
                if type(index) is not int or not 0 <= index < len(deck):
                    raise ValueError('Invalid deck_index')
                card = deck[index]
                if action == 'remove':
                    deck.pop(index)
                else:
                    upgraded = Card(**option['card'])
                    if upgraded.id != card.id or upgraded.upgrade != card.upgrade + 1:
                        raise ValueError('Upgrade must preserve card identity and increment its level')
                    deck[index] = upgraded
                    card = upgraded
            else:
                raise ValueError(f'Unsupported card operation: {action}')
            root_builds.append(replace(build, cards=tuple(deck)))
            choices.append(dict(action=action, card=card.to_dict()))
        root_builds.append(build)
        choices.append(dict(action='skip', card=None))
        root_count = len(root_builds)
        future = request['next_floors']
        if not isinstance(future, list) or len(future) > 2:
            raise ValueError('next_floors must contain zero to two floor distributions')
        boss = request.get('long_targets', request.get('boss_targets'))
        long_room = request.get('long_target_room', 'Boss')
        long_aggregation = request.get('long_target_aggregation', 'mean')
        if long_aggregation not in ('mean', 'max') or (long_aggregation == 'max' and long_room != 'Boss'):
            raise ValueError('Long target aggregation must be mean, or max for Boss targets')
        terminal = request.get('terminal', False)
        if type(terminal) is not bool:
            raise ValueError('terminal must be boolean')
        encounter_act = request.get('encounter_act_id', build.act_id)
        if encounter_act not in self.catalog.acts or (encounter_act != build.act_id
                and self.catalog.acts[encounter_act]['act'] != build.act + 1):
            raise ValueError('Encounter projection must be the current or next act')
        if terminal:
            if boss or future or build.act != max(a['act'] for a in self.catalog.acts.values()):
                raise ValueError('Terminal scoring requires the final act and no future targets')
            depth = 0
        elif long_room not in ('Elite', 'Boss'):
            raise ValueError('Long target must be Elite or Boss')

        def validate_targets(weights, room=None):
            if not isinstance(weights, dict) or not weights:
                raise ValueError('Encounter distribution must be nonempty')
            for target, w in weights.items():
                positive(w, 'encounter weight')
                if f'{encounter_act}:{target}' not in self.scorer.predictor.trained_targets:
                    raise ValueError(f'Uncovered target: {encounter_act}:{target}')
                if room and not any(e['id'] == target and e['room_type'] == room
                                    for e in self.catalog.acts[encounter_act]['encounters']):
                    raise ValueError(f'Long targets must contain {room} encounters')
            positive(sum(weights.values()), 'encounter weight sum')

        if not terminal:
            validate_targets(boss, long_room)
        for floor in future:
            p = floor.get('combat_probability', 1.0)
            positive(p, 'combat_probability', zero=True)
            if p > 1:
                raise ValueError('combat_probability must be <= 1')
            if p or floor.get('targets'):
                validate_targets(floor['targets'])

        cache, missing, warnings = {}, set(), set()
        stats = {'scored_build_distributions': 0, 'cache_hits': 0, 'upgrade_candidates': 0,
                 'upgrade_branches': 0, 'per_depth': []}

        def losses(builds, targets):
            if terminal:
                return [0.0] * len(builds)
            distribution = canonical(targets)
            keys = [(b.id, distribution) for b in builds]
            pending = {}
            for key, b in zip(keys, builds):
                if key not in cache and key not in pending:
                    pending[key] = b
                else:
                    stats['cache_hits'] += 1
            entries = list(pending.items())
            for start in range(0, len(entries), c['inference_batch_size']):
                batch = entries[start:start+c['inference_batch_size']]
                projection = {'encounter_act_id': encounter_act} if encounter_act != build.act_id else {}
                results = self.scorer.score_many([dict(build=b.to_dict(), max_hp=hp, targets=targets, **projection)
                                                  for _, b in batch], strict=c['strict_features'])
                for (key, _), result in zip(batch, results):
                    cache[key] = result['expected_hp_loss']
                    missing.update(result['untrained_features'])
                    warnings.update(result.get('warnings', []))
            stats['scored_build_distributions'] += len(entries)
            return [cache[k] for k in keys]

        # Fail explicitly when actual rewards exceed the model's legal domain.
        for b in root_builds:
            self.catalog.validate(b)
        short = [0.0] * root_count
        short_details = [[] for _ in range(root_count)]
        short_combat_weight = 0.0
        for i, floor in enumerate(future):
            probability = floor.get('combat_probability', 1.0)
            short_combat_weight += c['short_floor_weights'][i] * probability
            values = losses(root_builds, floor['targets']) if probability else [0.0]*root_count
            for root in range(root_count):
                expected = probability * values[root]
                short[root] += c['short_floor_weights'][i] * expected
                short_details[root].append(dict(expected_hp_loss=expected, combat_probability=probability,
                                                targets=floor.get('targets', {}), weight=c['short_floor_weights'][i]))
        # The final root is always the unchanged deck, even for forced choices.
        # Health is used only for this policy budget, never as a model input.
        # Count expected battle losses, without the scoring floor weights.
        budget = None
        if budget_hp is not None and not terminal:
            budget = survival_budget(budget_hp, future, boss, lambda targets: losses([build], targets)[0],
                safety_margin=c['elite_safety_margin'] if long_room == 'Elite' else c['boss_safety_margin'],
                sequential=long_room == 'Boss' and long_aggregation == 'max')
        weighting = score_weighting(short[-1] / short_combat_weight if short_combat_weight else None, c, budget=budget)
        if short_combat_weight and c['short_reduction'] == 'mean':
            # Conditional mean per possible battle. Shops/rests are not
            # zero-damage battles; uncertain combat probability contributes
            # equally to the numerator and the effective battle count.
            short = [s / short_combat_weight for s in short]
        def long_losses(builds):
            # Re-evaluate the harder Boss for every candidate and rollout node.
            # Short-term distributions still use their ordinary weighted mean.
            if long_aggregation == 'max' and not terminal:
                values = [losses(builds, {target: 1.0}) for target in boss]
                return [max(row) for row in zip(*values)]
            return losses(builds, boss)

        initial_boss = long_losses(root_builds)
        frontiers = [[Node(b, [], loss)] for b, loss in zip(root_builds, initial_boss)]
        pool = self.pool() if depth else []
        sample_count = c['samples_per_parent']
        if depth and not pool:
            raise ValueError('No eligible reward cards with positive rarity weight')
        if depth and max(len(b.cards) for b in root_builds) + depth > self.catalog.config['max_deck_size']:
            raise ValueError('Rollout could exceed model deck-size limit; reduce rollout_depth')

        # One upgrade branch per parent, selected by current target loss.
        # Cache by the full ordered build: deck_index in the path must still
        # identify the same owned instance when equal IDs have different state.
        upgrade_cache = {}

        def best_upgrades(frontiers):
            probes, spans = [], []
            seen = set()
            for parents in frontiers:
                for parent in parents:
                    if parent.upgrades >= c['rollout_max_upgrades']:
                        continue
                    b = parent.build
                    if b in upgrade_cache or b in seen:
                        continue
                    seen.add(b)
                    start = len(probes)
                    instances = set()
                    for index, card in enumerate(b.cards):
                        if card in instances or card.upgrade >= self.catalog.cards[card.id]['max_upgrade_level']:
                            continue
                        instances.add(card)
                        upgraded = replace(card, upgrade=card.upgrade+1)
                        cards = list(b.cards)
                        cards[index] = upgraded
                        candidate = replace(b, cards=tuple(cards))
                        self.catalog.validate(candidate)
                        probes.append((candidate, index, upgraded))
                    spans.append((b, start, len(probes)))
            values = long_losses([row[0] for row in probes]) if probes else []
            stats['upgrade_candidates'] += len(probes)
            for b, start, end in spans:
                best = min(range(start, end), key=lambda i: (values[i], probes[i][1])) if start < end else None
                upgrade_cache[b] = probes[best] if best is not None else None

        def expand(frontiers, level):
            best_upgrades(frontiers)
            children, ranges = [], []
            for root, parents in enumerate(frontiers):
                for parent_index, parent in enumerate(parents):
                    # Same random offers for corresponding paths of all roots.
                    digest = hashlib.sha256(f'{seed}:{level}:{parent_index}'.encode()).digest()
                    rng = random.Random(int.from_bytes(digest, 'big'))
                    offered = sample_card_ids(pool, self.catalog.cards, c['rarity_weights'], sample_count, rng)
                    options = [None] + [Card(cid, int(rng.random() < c['upgrade_probability'] and
                                                     self.catalog.cards[cid]['max_upgrade_level'] >= 1)) for cid in offered]
                    start = len(children)
                    for card in options:
                        b = parent.build if card is None else replace(parent.build, cards=parent.build.cards+(card,))
                        children.append(Node(b, parent.path + [None if card is None else card.to_dict()],
                                             upgrades=parent.upgrades))
                    upgrade = upgrade_cache.get(parent.build) if parent.upgrades < c['rollout_max_upgrades'] else None
                    if upgrade is not None:
                        b, index, card = upgrade
                        children.append(Node(b, parent.path + [dict(action='upgrade', deck_index=index,
                            card=card.to_dict())], upgrades=parent.upgrades+1))
                        stats['upgrade_branches'] += 1
                    ranges.append((root, start, len(children)))
            values = long_losses([node.build for node in children])
            for node, value in zip(children, values):
                node.loss = value
            return children, ranges

        level = 0
        while level < depth:
            children, ranges = expand(frontiers, level)
            paired = level < 2*c['lookahead_pairs'] and level+1 < depth
            if paired:
                # Delay pruning until both future actions have been evaluated. All
                # roots get the same offers by positional path, independently
                # of their scores. The second step is part of the real depth,
                # not a phantom bonus or an extra card beyond the horizon.
                unpruned = [[] for _ in range(root_count)]
                for root, start, end in ranges:
                    unpruned[root].extend(children[start:end])
                grandchildren, grand_ranges = expand(unpruned, level+1)
                retained = [sorted(grandchildren[start:end], key=lambda n: n.loss)[:c['keep_per_parent']]
                            for _, start, end in grand_ranges]
                # grand_ranges follows the same root/parent order as children.
                frontiers = [[] for _ in range(root_count)]
                first_counts = [0]*root_count
                for root, start, end in ranges:
                    best = sorted(range(start, end),
                                  key=lambda i: (retained[i][0].loss, children[i].loss))[:c['keep_per_parent']]
                    first_counts[root] += len(best)
                    for i in best:
                        frontiers[root].extend(retained[i])
                stats['per_depth'].extend([
                    dict(depth=level+1, evaluated_paths=len(children), leaves_per_root=first_counts,
                         pruning='two_step'),
                    dict(depth=level+2, evaluated_paths=len(grandchildren),
                         leaves_per_root=[len(f) for f in frontiers], pruning='two_step')])
                level += 2
                continue
            frontiers = [[] for _ in range(root_count)]
            for root, start, end in ranges:
                # Stable ties prefer skip, sampled cards, then the upgrade.
                frontiers[root].extend(sorted(children[start:end], key=lambda node: node.loss)[:c['keep_per_parent']])
            stats['per_depth'].append(dict(depth=level+1, evaluated_paths=len(children),
                                           leaves_per_root=[len(f) for f in frontiers], pruning='one_step'))
            level += 1

        candidates = []
        for index, leaves in enumerate(frontiers):
            ranked = sorted(leaves, key=lambda node: node.loss)
            tails = aggregate_leaf_losses([node.loss for node in ranked], c)
            weights = tails.pop('weights')
            long = tails['long_expected_hp_loss']
            combined = weighting['short_weight']*short[index] + weighting['long_weight']*long
            candidates.append(dict(option_index=index, **choices[index],
                                   short_expected_hp_loss=short[index], short_score=-short[index], short_details=short_details[index],
                                   short_combat_weight=short_combat_weight,
                                   initial_boss_hp_loss=initial_boss[index] if long_room == 'Boss' else None,
                                   initial_long_hp_loss=initial_boss[index], **tails, long_score=-long,
                                   top_score=-tails['top_expected_hp_loss'], bottom_score=-tails['bottom_expected_hp_loss'],
                                   combined_score=-combined, leaf_count=len(leaves),
                                   leaves=[dict(build_id=node.build.id, path=node.path, upgrade_count=node.upgrades, target_hp_loss=node.loss,
                                                boss_hp_loss=node.loss if long_room == 'Boss' else None,
                                                aggregation_weight=weights[i])
                                           for i, node in enumerate(ranked)]))
        # Stable root ties favor skip; no random tie-breaking by reward order.
        ranked_options = sorted(candidates, key=lambda r: (-r['combined_score'], r['action'] != 'skip', r['option_index']))
        best = ranked_options[0]
        return dict(recommended_option_index=best['option_index'], recommended_action=best['action'], recommended_card=best['card'],
                    ranking=[r['option_index'] for r in ranked_options],
                    score_margin=best['combined_score']-ranked_options[1]['combined_score'] if len(ranked_options) > 1 else 0.0,
                    rollout_depth=depth, seed=seed, config=c, score_weighting=weighting, pool_card_ids=pool, candidates=candidates,
                    encounter_act_id=encounter_act, long_target_room=long_room, long_targets=boss,
                    long_target_aggregation=long_aggregation,
                    untrained_features=sorted(missing), warnings=sorted(warnings), stats=stats,
                    elapsed_seconds=time.perf_counter()-started,
                    interpretation='Best/worst tails against the declared Elite/Boss target pool, not an unbiased expectation of future rewards. Full-health model; future steps add cards, skip or upgrade one owned card. Upgrade opportunities are hypothetical, bounded by rollout_max_upgrades.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, help='One reward decision JSON')
    parser.add_argument('--output', help='Decision JSON (stdout by default)')
    parser.add_argument('--config', default=str(DEFAULT_CONFIG))
    parser.add_argument('--checkpoint', default=str(DEFAULT_CHECKPOINT))
    parser.add_argument('--device', default='cpu')
    args = parser.parse_args()
    config = load_config(args.config)
    import torch
    torch.set_num_threads(config['cpu_threads'])
    selector = RewardSelector(BuildScorer(args.checkpoint, args.device), config)
    result = selector.select(json.loads(Path(args.input).read_text()))
    result['checkpoint'] = str(Path(args.checkpoint).resolve())
    text = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        Path(args.output).write_text(text, encoding='utf-8')
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
