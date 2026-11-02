"""Risk-based public encounter targets for current and post-boss card evaluation."""
import math


def scoring_horizon(catalog, trained_targets, state, *, score_elites=None,
                    elite_loss_threshold=20.0, boss_after_act_floor=6):
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
                        long_targets={}, short_targets={}, projects_next_act=False, warnings=[],
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
        probe = score_elites(act_id, elites)
        elite_loss = probe['expected_hp_loss']
        if isinstance(elite_loss, bool) or not isinstance(elite_loss, (int, float)) or not math.isfinite(elite_loss) or elite_loss < 0:
            raise ValueError('Elite expected loss must be finite and nonnegative')
        warnings.extend(probe.get('warnings', []))
        warnings.extend('untrained_feature:' + key for key in probe.get('untrained_features', []))
        reason = 'elite_loss_above_threshold' if elite_loss > elite_loss_threshold else 'elite_loss_at_or_below_threshold'

    if reason == 'elite_loss_above_threshold':
        long_targets, room = elites, 'Elite'
    elif completed:
        # The next Boss is not public yet. Never use the old Boss or peek at
        # generated future state; compare the public next-act Boss mixture.
        long_targets, room = pool('Boss'), 'Boss'
    else:
        boss = state['visibleBoss']
        if not any(e['id'] == boss and e['room_type'] == 'Boss' for e in catalog.acts[act_id]['encounters']):
            raise ValueError('Visible boss is not a Boss encounter of the current act')
        if f'{act_id}:{boss}' not in trained_targets:
            raise ValueError(f'Uncovered target: {act_id}:{boss}')
        long_targets, room = {boss: 1.0}, 'Boss'
    return dict(mode=('next_act_' if completed else '') + ('elite_risk' if room == 'Elite' else 'boss'),
                projects_next_act=completed, encounter_act_id=act_id, long_target_room=room, long_targets=long_targets,
                short_targets=short_targets, target_reason=reason, estimated_elite_loss=elite_loss,
                elite_target_loss_threshold=elite_loss_threshold, boss_target_after_act_floor=boss_after_act_floor,
                evaluated_act_floor=act_floor, warnings=sorted(set(warnings)))
