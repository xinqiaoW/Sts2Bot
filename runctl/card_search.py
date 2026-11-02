"""One owner for Bot rollout depth, crisis expansion, and scoring diagnostics."""
from train.reward_policy import RewardSelector
from train.scoring_horizon import scoring_horizon
from .route_policy import next_floors


def rollout_plan(selector, config, floors_to_boss, *, fixed_depth=None, post_boss=False, terminal=False, crisis=False):
    if terminal:
        return 0, "terminal"
    extra = config["crisis_extra_depth"] if crisis else 0
    if fixed_depth is not None:
        return fixed_depth + extra, "fixed_reward"
    if post_boss:
        return min(6, config["post_boss_rollout_depth"] + extra), "post_boss"
    remaining = max(0, floors_to_boss - 1)
    depth = min(selector.depth_for(floors_to_boss), config["max_rollout_depth"], remaining)
    return min(depth + extra, config["max_rollout_depth"], remaining), "distance_to_boss"


def search_card_builds(self, state, build, explicit, *, fixed_depth=None):
    # An empty offer list evaluates only the current build's skip branch.
    # Shops still need the same rollout risk definition after cards sell out.
    normal = RewardSelector(self.model.scorer, self.reward_config)
    horizon = scoring_horizon(self.model.catalog, self.model.scorer.predictor.trained_targets, state,
        elite_loss_threshold=self.config['elite_target_loss_threshold'],
        elite_safety_margin=self.config['elite_safety_margin'],
        short_floors=lambda: next_floors(state, lambda r, n: self.targets(state, r, n), self.config['unknown_combat_probability']),
        boss_after_act_floor=self.config['boss_target_after_act_floor'],
        score_elites=lambda act_id, targets: self.model.scorer.score_many([
            dict(build=build.to_dict(), max_hp=state['maxHp'], targets=targets, encounter_act_id=act_id)], strict=False)[0])
    future = horizon['next_floors']
    depth_args = dict(fixed_depth=fixed_depth, post_boss=horizon['projects_next_act'],
                      terminal=horizon['mode'] == 'terminal')
    depth, mode = rollout_plan(normal, self.config, state['floorsToBoss'], **depth_args)
    request = dict(build=build.to_dict(), max_hp=state['maxHp'], budget_hp=state['hp'], options=explicit,
        floors_to_boss=state['floorsToBoss'], rollout_depth=depth,
        next_floors=future, long_targets=horizon['long_targets'], long_target_room=horizon['long_target_room'],
        long_target_aggregation=horizon.get('long_target_aggregation', 'mean'),
        encounter_act_id=horizon['encounter_act_id'], terminal=horizon['mode'] == 'terminal')
    result = normal.select(request)
    projected_loss = min(c['long_expected_hp_loss'] for c in result['candidates'])
    crisis = projected_loss > self.config['crisis_boss_loss_threshold']
    if crisis:
        expanded = dict(self.reward_config, samples_per_parent=self.config['crisis_samples_per_parent'],
                        keep_per_parent=self.config['crisis_keep_per_parent'])
        request['rollout_depth'], _ = rollout_plan(normal, self.config, state['floorsToBoss'],
                                                  crisis=True, **depth_args)
        if expanded != self.reward_config or request['rollout_depth'] != depth:
            result = RewardSelector(self.model.scorer, expanded).select(request)
    self.model.warnings.extend(result['warnings'])
    self.model.warnings.extend('untrained_feature:' + k for k in result['untrained_features'])
    self.model.warnings.extend(horizon['warnings'])
    self.last_report.update(crisis=crisis, projected_long_loss=projected_loss,
        projected_boss_loss=projected_loss if horizon['long_target_room'] == 'Boss' else None,
        scoring_horizon=horizon,
        rollout_depth_mode=mode,
        crisis_basis='best_normal_rollout_long_loss',
        crisis_target_room=horizon['long_target_room'],
        rollout_depth=result['rollout_depth'], samples_per_parent=result['config']['samples_per_parent'],
        keep_per_parent=result['config']['keep_per_parent'],
        lookahead_pairs=result['config']['lookahead_pairs'], rollout_max_upgrades=result['config']['rollout_max_upgrades'],
        stats=result['stats'],
        score_weighting=result['score_weighting'],
        long_tail_summaries=[{k: c[k] for k in ('option_index', 'action', 'card',
            'top_expected_hp_loss', 'bottom_expected_hp_loss', 'long_expected_hp_loss',
            'top_leaf_count', 'bottom_leaf_count', 'selected_leaf_count')}
            for c in result['candidates']])
    return result

