"""Risk-based public encounter targets for current and post-boss card evaluation."""
import math


def survival_budget(current_hp, future, targets, score, *, safety_margin=0.0, sequential=False):
    """Expected loss budget, independent of scoring floor weights/mean reduction.

    `score` predicts the unchanged full-health build against a distribution.
    One target fight (or every known consecutive Boss) is counted once when
    it also appears in the short window. No speculative healing is credited.
    """
    def nonnegative(value, name):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f'{name} must be finite and nonnegative')
        return value

    nonnegative(current_hp, 'Budget HP')
    nonnegative(safety_margin, 'Safety margin')
    if not isinstance(targets, dict) or not targets:
        raise ValueError('Budget targets must be nonempty')

    def weights(distribution):
        if not distribution:
            raise ValueError('Budget battle distribution must be nonempty')
        for value in distribution.values():
            nonnegative(value, 'Budget encounter weight')
            if value == 0:
                raise ValueError('Budget encounter weight must be positive')
        total = sum(distribution.values())
        if not math.isfinite(total):
            raise ValueError('Budget encounter weight sum must be finite')
        return total

    def loss(distribution):
        weights(distribution)
        return nonnegative(score(distribution), 'Budget expected loss')

    target_loss = sum(loss({t: 1.0}) for t in targets) if sequential else loss(targets)
    # A pool represents one uncertain encounter; known consecutive Bosses
    # represent several distinct fights. Repeated elites are not all erased.
    overlap_left = float(len(targets) if sequential else 1)
    short_loss = overlap_loss = 0.0
    for floor in future:
        probability = nonnegative(floor.get('combat_probability', 1.0), 'Budget combat probability')
        if probability > 1:
            raise ValueError('Budget combat probability must be <= 1')
        if not probability:
            continue
        distribution = floor['targets']
        total = weights(distribution)
        short_loss += probability * loss(distribution)
        overlapping = {t: w for t, w in distribution.items() if t in targets}
        if overlapping and overlap_left > 0:
            count = min(overlap_left, probability * sum(overlapping.values()) / total)
            overlap_loss += count * loss(overlapping)
            overlap_left -= count
    before_target = max(0.0, short_loss - overlap_loss)
    remaining = current_hp - before_target - target_loss
    # Normalized pool weights can put an exact zero a few ulps above zero.
    if math.isclose(remaining, safety_margin, rel_tol=0.0, abs_tol=1e-9):
        remaining = safety_margin
    return dict(current_hp=current_hp, short_total_expected_hp_loss=short_loss,
                short_target_overlap_expected_hp_loss=overlap_loss,
                short_before_target_expected_hp_loss=before_target,
                target_expected_hp_loss=target_loss, target_aggregation='sum' if sequential else 'mean',
                remaining_hp=remaining, safety_margin=safety_margin, sufficient=remaining > safety_margin)


def scoring_horizon(catalog, trained_targets, state, *, score_elites=None,
                    elite_loss_threshold=20.0, boss_after_act_floor=6, short_floors=None,
                    elite_safety_margin=0.0):
    act_id, act = state['actId'], state['act']
    if catalog.acts[act_id]['act'] != act:
        raise ValueError('Scoring horizon act mismatch')
    count = state.get('normalCombatsCompleted')
    if count is not None and (type(count) is not int or count < 0):
        raise ValueError('normalCombatsCompleted must be a nonnegative integer')
    completed = state.get('actBossDefeated', False)
    if type(completed) is not bool:
        raise ValueError('actBossDefeated must be boolean')
    if isinstance(elite_loss_threshold, bool) or not isinstance(elite_loss_threshold, (int, float)) or not math.isfinite(elite_loss_threshold) or elite_loss_threshold < 0:
        raise ValueError('elite_loss_threshold must be finite and nonnegative')
    if type(boss_after_act_floor) is not int or boss_after_act_floor < 0:
        raise ValueError('boss_after_act_floor must be a nonnegative integer')
    act_floor = state.get('actFloor')
    if act_floor is not None and (type(act_floor) is not int or act_floor < 0):
        raise ValueError('actFloor must be a nonnegative integer')
    warnings = []
    if completed:
        next_acts = [key for key, value in catalog.acts.items() if value['act'] == act + 1]
        if not next_acts:
            if act != max(value['act'] for value in catalog.acts.values()):
                raise ValueError('Next act is missing from the encounter catalog')
            return dict(mode='terminal', encounter_act_id=act_id, long_target_room=None,
                        long_targets={}, short_targets={}, next_floors=[], projects_next_act=False, warnings=[],
                        target_reason='terminal', estimated_elite_loss=None)
        if len(next_acts) != 1:
            raise ValueError('Next act public pool is ambiguous; an explicit mixture is required')
        act_id, act, count, act_floor = next_acts[0], act + 1, 0, 0
    weak = count is not None and count < (3 if act == 1 else 2)

    def pool(room, weak_only=None):
        ids = [e['id'] for e in catalog.acts[act_id]['encounters'] if e['room_type'] == room
               and (weak_only is None or e['weak'] == weak_only)]
        covered = [tid for tid in ids if f'{act_id}:{tid}' in trained_targets]
        if len(covered) != len(ids):
            warnings.append(f'uncovered_encounters:{act_id}:{sorted(set(ids)-set(covered))}')
        if not covered:
            raise ValueError(f'No trained {room} encounter for scoring horizon {act_id}')
        return dict.fromkeys(covered, 1 / len(covered))

    # The ordinary-monster pool is independent of the long-term target switch.
    short_targets = pool('Monster', True) if weak else None
    future = ([dict(targets=short_targets, combat_probability=1.0)] if short_targets else []) if short_targets is not None else (
        short_floors() if callable(short_floors) else short_floors if short_floors is not None else [])
    budget_hp = state.get('hp')
    if budget_hp is not None and (isinstance(budget_hp, bool) or not isinstance(budget_hp, (int, float))
            or not math.isfinite(budget_hp) or budget_hp < 0 or budget_hp > state.get('maxHp', float('inf'))):
        raise ValueError('Budget HP must be finite, nonnegative and no greater than maxHp')
    if budget_hp is None:
        warnings.append('missing_current_hp:legacy_elite_threshold')
    elite_budget = None
    elite_loss = None
    if act_floor is None:
        reason = 'missing_act_floor'
        warnings.append('missing_act_floor_for_target_switch:using_boss')
    elif act_floor > boss_after_act_floor:
        reason = 'after_act_floor_limit'
    else:
        if score_elites is None:
            raise ValueError('Early-act target selection requires an elite loss estimate')
        elites = pool('Elite')
        cache = {}
        def probe_targets(targets):
            key = tuple(sorted(targets.items()))
            if key not in cache:
                cache[key] = score_elites(act_id, targets)
                warnings.extend(cache[key].get('warnings', []))
                warnings.extend('untrained_feature:' + k for k in cache[key].get('untrained_features', []))
            return cache[key]

        probe = probe_targets(elites)
        elite_loss = probe['expected_hp_loss']
        if isinstance(elite_loss, bool) or not isinstance(elite_loss, (int, float)) or not math.isfinite(elite_loss) or elite_loss < 0:
            raise ValueError('Elite expected loss must be finite and nonnegative')
        if budget_hp is not None:
            elite_budget = survival_budget(budget_hp, future, elites,
                lambda targets: probe_targets(targets)['expected_hp_loss'], safety_margin=elite_safety_margin)
            reason = 'elite_budget_sufficient' if elite_budget['sufficient'] else 'elite_budget_insufficient'
        else:
            reason = 'elite_loss_above_threshold' if elite_loss > elite_loss_threshold else 'elite_loss_at_or_below_threshold'

    aggregation = 'mean'
    if reason in ('elite_loss_above_threshold', 'elite_budget_insufficient'):
        long_targets, room = elites, 'Elite'
    elif completed:
        # The next Boss is not public yet. Never use the old Boss or peek at
        # generated future state; compare the public next-act Boss mixture.
        long_targets, room = pool('Boss'), 'Boss'
    else:
        bosses = state.get('remainingBosses', [state['visibleBoss']])
        if (not isinstance(bosses, list) or not 1 <= len(bosses) <= 2
                or any(not isinstance(b, str) for b in bosses) or len(set(bosses)) != len(bosses)
                or bosses[0] != state['visibleBoss']):
            raise ValueError('remainingBosses must list one or two distinct Bosses, next visible Boss first')
        for boss in bosses:
            if not any(e['id'] == boss and e['room_type'] == 'Boss' for e in catalog.acts[act_id]['encounters']):
                raise ValueError('Visible boss is not a Boss encounter of the current act')
            if f'{act_id}:{boss}' not in trained_targets:
                raise ValueError(f'Uncovered target: {act_id}:{boss}')
        long_targets, room = dict.fromkeys(bosses, 1.0), 'Boss'
        aggregation = 'max' if len(bosses) > 1 else 'mean'
    return dict(mode=('next_act_' if completed else '') + ('elite_risk' if room == 'Elite' else 'boss'),
                projects_next_act=completed, encounter_act_id=act_id, long_target_room=room, long_targets=long_targets,
                long_target_aggregation=aggregation,
                elite_survival_budget=elite_budget, next_floors=future,
                short_targets=short_targets, target_reason=reason, estimated_elite_loss=elite_loss,
                elite_target_loss_threshold=elite_loss_threshold, boss_target_after_act_floor=boss_after_act_floor,
                evaluated_act_floor=act_floor, warnings=sorted(set(warnings)))
