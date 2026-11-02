"""Public encounter pools for early-act and post-boss card evaluation."""


def scoring_horizon(catalog, trained_targets, state):
    act_id, act = state['actId'], state['act']
    if catalog.acts[act_id]['act'] != act:
        raise ValueError('Scoring horizon act mismatch')
    count = state.get('normalCombatsCompleted')
    if count is not None and (type(count) is not int or count < 0):
        raise ValueError('normalCombatsCompleted must be a nonnegative integer')
    completed = state.get('actBossDefeated', False)
    if type(completed) is not bool:
        raise ValueError('actBossDefeated must be boolean')
    warnings = []
    if completed:
        next_acts = [key for key, value in catalog.acts.items() if value['act'] == act + 1]
        if not next_acts:
            if act != max(value['act'] for value in catalog.acts.values()):
                raise ValueError('Next act is missing from the encounter catalog')
            return dict(mode='terminal', encounter_act_id=act_id, long_target_room=None,
                        long_targets={}, short_targets={}, warnings=[])
        if len(next_acts) != 1:
            raise ValueError('Next act public pool is ambiguous; an explicit mixture is required')
        act_id, act, count = next_acts[0], act + 1, 0
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

    if weak:
        long_targets, short_targets = pool('Elite'), pool('Monster', True)
        room = 'Elite'
    else:
        boss = state['visibleBoss']
        if not any(e['id'] == boss and e['room_type'] == 'Boss' for e in catalog.acts[act_id]['encounters']):
            raise ValueError('Visible boss is not a Boss encounter of the current act')
        if f'{act_id}:{boss}' not in trained_targets:
            raise ValueError(f'Uncovered target: {act_id}:{boss}')
        long_targets, short_targets, room = {boss: 1.0}, None, 'Boss'
    return dict(mode='next_act_weak_pool' if completed else 'weak_pool' if weak else 'boss',
                encounter_act_id=act_id, long_target_room=room, long_targets=long_targets,
                short_targets=short_targets, warnings=warnings)
