"""Beam planning over visible map topology and public encounter mixtures only."""
from dataclasses import dataclass


@dataclass(frozen=True)
class PathState:
    node: tuple
    hp: float
    value: float
    path: tuple
    normal_count: float = 0


def plan_route(state, options, losses, config):
    nodes = {(p['row'], p['col']): p for p in state['map']}
    hp_max = state['maxHp']

    def visit(previous, key):
        point = nodes[key]
        room = point['type']
        hp, value, normal_count = previous.hp, previous.value, previous.normal_count
        if room in ('Monster', 'Elite', 'Boss', 'Unknown'):
            loss = losses.get(room, 0)
            if room in ('Monster', 'Unknown'):
                weak_fraction = min(1, max(0, (3 if state.get('act', 1) == 1 else 2)-normal_count))
                loss = weak_fraction*losses.get('MonsterWeak', losses['Monster']) + (1-weak_fraction)*losses['Monster']
                normal_count += config['unknown_combat_probability'] if room == 'Unknown' else 1
            if room == 'Unknown':
                loss *= config['unknown_combat_probability']
                value += (1-config['unknown_combat_probability']) * config['route_event_value']
            hp -= loss
            value -= loss
            if room == 'Elite': value += config['route_elite_reward']
            if room == 'Monster': value += config['route_card_reward']
            # Full-health predictions are not calibrated low-HP death odds.
            # This is an explicit risk heuristic, not a probability claim.
            value -= config['route_risk_weight'] * max(0, .25*hp_max-hp)
            if hp <= 0: value -= 1000 + abs(hp)*10
        elif room == 'RestSite':
            healed = min(max(0, hp_max-hp), .3*hp_max)
            hp += healed
            value += max(healed, config['route_card_reward'])
        elif room == 'Treasure':
            value += config['route_elite_reward']
        elif room == 'Shop':
            value += config['route_shop_value'] * min(2, state['gold']/150)
        elif room not in ('Ancient', 'Unassigned'):
            raise ValueError('Unsupported visible map type: ' + room)
        return PathState(key, hp, value, previous.path+(key,), normal_count)

    plans = []
    for option in options:
        root = (option['row'], option['col'])
        if root not in nodes:
            raise ValueError('Legal map option missing from visible map')
        frontier = [visit(PathState(root, state['hp'], 0, (), state.get('normalCombatsCompleted', 0)), root)]
        finished = []
        for _ in range(len(nodes)+1):
            children = []
            for previous in frontier:
                successors = nodes[previous.node]['children']
                if not successors:
                    finished.append(previous)
                for child in successors:
                    key = (child['row'], child['col'])
                    if key in previous.path:
                        raise ValueError('Visible map contains a cycle')
                    children.append(visit(previous, key))
            if not children: break
            frontier = sorted(children, key=lambda p: (p.value, p.hp), reverse=True)[:config['route_beam_width']]
        if not finished:
            raise ValueError('Visible route has no terminal node')
        best = max(finished, key=lambda p: (p.value, p.hp))
        plans.append(dict(index=option['index'], value=best.value, estimated_hp=best.hp, path=best.path))
    return max(plans, key=lambda p: (p['value'], -p['index']))['index'], plans


def next_floors(state, target_for, unknown_probability):
    nodes = {(p['row'], p['col']): p for p in state['map']}
    current = state['currentNode']
    if current is None: return []
    frontier = {((current['row'], current['col']), state.get('normalCombatsCompleted')): 1.0}
    floors = []
    # Normally inspect two map layers. If both have no possible combat,
    # extend through visible topology until the first possible fight instead
    # of making short-term strength disappear behind shops/rests/events.
    for layer in range(len(nodes)+1):
        after = {}
        for (key, count), probability in frontier.items():
            children = nodes.get(key, {}).get('children', [])
            for child in children:
                pos = (child['row'], child['col'])
                after[(pos, count)] = after.get((pos, count), 0) + probability/len(children)
        if not after: break
        targets = {}
        frontier = {}
        for (key, count), probability in after.items():
            room = nodes[key]['type']
            combat = unknown_probability if room == 'Unknown' else (1 if room == 'Monster' else 0)
            updated = count+1 if count is not None else None
            if combat:
                frontier[(key, updated)] = frontier.get((key, updated), 0) + probability*combat
            if combat < 1:
                frontier[(key, count)] = frontier.get((key, count), 0) + probability*(1-combat)
            if room == 'Unknown': room, probability = 'Monster', probability*combat
            if probability == 0 or room not in ('Monster', 'Elite', 'Boss'): continue
            for target, weight in target_for(room, count).items():
                targets[target] = targets.get(target, 0) + probability*weight
        floor = dict(targets=targets, combat_probability=min(1., sum(targets.values())))
        if layer < 2:
            floors.append(floor)
        elif targets:
            floors = [floor]
        if layer >= 1 and any(f['combat_probability'] > 0 for f in floors):
            return floors
    return floors
