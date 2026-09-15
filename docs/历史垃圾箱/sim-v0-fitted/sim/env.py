"""Abstract Silent A10 run environment.

One episode is a full run (three acts). The agent decides out of combat only:

``ancient``      pick one of three offered relics          ``('relic', relic_id)``
``map``          choose the next map node                  ``('go', node_id)``
``card_reward``  take one offered card or skip             ``('card', index)`` / ``('skip',)``
``rest``         heal or upgrade one card                  ``('heal',)`` / ``('smith', deck_index)``
``shop``         buy a card/relic, remove a card, or leave ``('buy_card', i)`` / ``('buy_relic', i)`` / ``('purge', deck_index)`` / ``('leave',)``

Treasure rooms, events and elite/boss relics resolve automatically from the
fitted tables (events replay a random recorded human outcome of that event).
Combat is delegated to a :class:`sim.oracle.CombatOracle`: entering a fight sets
``pending_combat``; with an oracle attached the env resolves it immediately,
otherwise a vectorised driver batches requests and calls ``resolve_combat``.

Potions are ignored (conservative). Card enchantments and rest-site options
granted by relics (DIG, LIFT, ...) are not modelled in v0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import math

import numpy as np

from damage_model.catalog import COUNTER_DOMAINS, Catalog
from damage_model.schema import Build, Card, Relic

from .map import ActMap, generate_map
from .oracle import CombatOracle, CombatRequest, CombatResult

PHASES = ('ancient', 'map', 'combat', 'card_reward', 'rest', 'shop', 'done')
BASIC_CARDS = {'STRIKE_SILENT', 'DEFEND_SILENT'}
SHARED_ANCIENT = 'DARV'


@dataclass
class CardInstance:
    id: str
    upgrade: int = 0
    state: tuple = ()   # saved card state (damage_model.card_state), only Mad Science needs one


@dataclass
class ShopStock:
    cards: list[dict] = field(default_factory=list)    # {'id', 'price'}
    relics: list[dict] = field(default_factory=list)   # {'id', 'price'}
    purge_price: int = 100


def _weights(hist: dict, keys=None):
    items = [(k, v) for k, v in hist.items() if keys is None or k in keys]
    if not items:
        return [], np.array([])
    ks, vs = zip(*items)
    vs = np.asarray(vs, dtype=float)
    return list(ks), vs / vs.sum()


class RunEnv:
    def __init__(self, tables: dict, catalog: Catalog, oracle: CombatOracle | None = None, seed=None,
                 record_history=True):
        self.tables, self.catalog, self.oracle = tables, catalog, oracle
        self.structure = tables['structure']
        self.rng = np.random.default_rng(seed)
        self.record_history = record_history
        self.allowed_cards = set(catalog.card_pool) | set(catalog.raw['character']['starting_deck'])
        self.allowed_relics = set(catalog.relic_pool)
        self.card_info = catalog.cards
        self.relic_info = catalog.relics
        self.act_encounters = {a: {e['id']: e for e in spec['encounters']} for a, spec in catalog.acts.items()}
        self._prepare_tables()
        self.reset(seed)

    # ------------------------------------------------------------------ setup
    def _prepare_tables(self):
        t = self.tables
        self._act1 = _weights(t['act1_choice'])
        self._unknown = {a: _weights(v) for a, v in t['unknown_resolution'].items()}
        self._pools = {}
        for act, hist in t['encounters'].items():
            pools = {'weak': {}, 'normal': {}, 'elite': {}, 'boss': {}}
            for key, n in hist.items():
                rt, enc = key.split(':', 1)
                if rt == 'monster':
                    pools['weak' if enc.endswith('_WEAK') else 'normal'][enc] = n
                elif rt in ('elite', 'boss'):
                    pools[rt][enc] = n
            self._pools[act] = {k: _weights(v) for k, v in pools.items()}
        self._gold = {}
        for act, hist in t['gold'].items():
            per_type = {}
            for key, n in hist.items():
                rt, g = key.split(':')
                per_type.setdefault(rt, {})[int(g)] = n
            self._gold[act] = {rt: _weights({k: v for k, v in h.items() if k <= 60 or rt == 'boss'}) for rt, h in per_type.items()}
        self._card_rarity = {k: _weights(v, ('Common', 'Uncommon', 'Rare')) for k, v in t['card_reward_rarity'].items()}
        self._relic_rarity = {k: _weights(v) for k, v in t['relic_rarity'].items()}
        shop = t['shop']
        self._shop_n = _weights({int(k): v for k, v in shop['n_cards'].items() if 4 <= int(k) <= 7})
        self._shop_mix = _weights(shop['card_mix'])
        self._shop_relic_rarity = _weights(shop['relic_rarity'], ('Common', 'Uncommon', 'Rare', 'Shop'))
        self._prices = {}
        for key, hist in shop['prices'].items():
            values = sorted((int(p), n) for p, n in hist.items())
            total = sum(n for _, n in values)
            acc, median = 0, values[-1][0]
            for p, n in values:
                acc += n
                if acc >= total / 2:
                    median = p
                    break
            self._prices[key] = median
        self._prices.setdefault('card:SILENT:Common', 50); self._prices.setdefault('card:SILENT:Uncommon', 75)
        self._prices.setdefault('card:SILENT:Rare', 150); self._prices.setdefault('card:COLORLESS:Uncommon', 90)
        self._prices.setdefault('card:COLORLESS:Rare', 180)
        for rarity, default in (('Common', 150), ('Uncommon', 250), ('Rare', 300), ('Shop', 150)):
            self._prices.setdefault(f'relic:{rarity}', default)
        # Sale cards are recorded at half price; drop them from the medians above by
        # using the upper cluster. The medians already sit in the full-price cluster.
        self._ancients = {a: _weights(v, set(self.catalog.ancients)) for a, v in t['ancients'].items()}
        self._ancient_offers = {a: _weights(v, set(self.catalog.ancients[a]['possible_relics']))
                                for a, v in t['ancient_offers'].items() if a in self.catalog.ancients}
        self._events = {a: _weights({e: n for e, n in v.items() if e in t['event_outcomes']}) for a, v in t['events'].items()}
        self._relic_max_hp = {k: _weights({int(d): n for d, n in v.items()}) for k, v in t['relic_max_hp'].items()}
        self._row_weights = {}
        if self.structure['map_generator'].get('mode', 'fitted_rows') == 'fitted_rows':
            for act, hist in t['row_types'].items():
                per_row = {}
                for key, n in hist.items():
                    floor, node_type = key.split(':')
                    per_row.setdefault(int(floor), {})[node_type] = n
                self._row_weights[act] = per_row

    def reset(self, seed=None):
        if seed is not None:
            self.rng = np.random.default_rng(seed)
        s = self.structure['start']
        self.hp, self.max_hp, self.gold = s['hp'], s['max_hp'], s['gold']
        self.deck = [CardInstance(c) for c in self.catalog.raw['character']['starting_deck']] + [CardInstance('ASCENDERS_BANE')]
        self.relics = list(self.catalog.raw['character']['starting_relics'])
        self.relic_states = {r: self._sample_relic_state(r) for r in self.relics}
        self.ancient_history = []
        self.purges = 0
        self.done, self.won = False, False
        self.total_floor = 0
        self.history = []
        self.pending_combat = None
        self.phase = 'done'
        self.options = []
        self.shop = None
        acts, probs = self._act1
        self.act_sequence = [acts[self.rng.choice(len(acts), p=probs)], 'HIVE', 'GLORY']
        self.act_index = -1
        self._begin_act()
        return self.observation()

    # ------------------------------------------------------------------ helpers
    def _sample_relic_state(self, relic_id):
        domains = COUNTER_DOMAINS.get(relic_id, {})
        state = {k: domain[int(self.rng.integers(len(domain)))] for k, domain in sorted(domains.items())}
        if relic_id == 'WONGOS_MYSTERY_TICKET':
            state['GaveRelic'] = state['CombatsFinished'] >= 5
        return tuple(sorted(state.items()))

    def _choice(self, table):
        keys, probs = table
        if not keys:
            return None
        return keys[self.rng.choice(len(keys), p=probs)]

    def _sample_encounter(self, kind):
        keys, probs = self._pools[self.act_id][kind]
        if not keys:
            return None
        keys = list(keys); probs = np.array(probs)
        if self.last_encounter in keys and len(keys) > 1:
            probs[keys.index(self.last_encounter)] = 0
            probs = probs / probs.sum()
        return keys[self.rng.choice(len(keys), p=probs)]

    def _sample_cards(self, rarity_table, n, pool='silent', exclude=()):
        pools = self.tables['pools'][pool]
        out = []
        for _ in range(n):
            for _attempt in range(20):
                rarity = self._choice(rarity_table)
                candidates = [c for c in pools.get(rarity, []) if c not in out and c not in exclude]
                if candidates:
                    out.append(candidates[int(self.rng.integers(len(candidates)))])
                    break
        return out

    def _sample_relic(self, rarity_table, allow_shop=False):
        pools = self.tables['pools']['relic']
        for _attempt in range(30):
            rarity = self._choice(rarity_table)
            candidates = [r for r in pools.get(rarity, []) if r not in self.relics]
            if candidates:
                return candidates[int(self.rng.integers(len(candidates)))]
        return None

    def _card_rarity_table(self, room_type):
        return self._card_rarity.get(f'{self.act_id}:{room_type}') or self._card_rarity.get(f'{self.act_id}:monster')

    # ------------------------------------------------------------------ act flow
    def _begin_act(self):
        self.act_index += 1
        self.act_id = self.act_sequence[self.act_index]
        self.act_spec = self.structure['acts'][self.act_id]
        self.act = self.act_spec['act']
        self.map: ActMap = generate_map(self.rng, self.act_spec, self.structure, self._row_weights.get(self.act_id))
        self.node = None
        self.floor = 0
        self.fights_in_act = 0
        self.boss_fights_done = 0
        self.last_encounter = None
        self.boss_encounters = []
        if self.act_index > 0:
            heal = math.floor(self.structure['inter_act_heal_ratio'] * (self.max_hp - self.hp))
            self.hp = min(self.max_hp, self.hp + heal)
        # Ancient floor.
        allowed = set(self.catalog.acts[self.act_id]['ancients']) | ({SHARED_ANCIENT} if self.act > 1 else set())
        allowed -= {a for _, a, _ in self.ancient_history if a in self.catalog.shared_ancients}
        table = self._ancients.get(self.act_id, ([], np.array([])))
        keys = [k for k in table[0] if k in allowed]
        if keys:
            probs = np.array([table[1][table[0].index(k)] for k in keys]); probs /= probs.sum()
            self.ancient = keys[self.rng.choice(len(keys), p=probs)]
        else:
            self.ancient = sorted(allowed)[0]
        offers = self._ancient_offers.get(self.ancient)
        possible = [r for r in self.catalog.ancients[self.ancient]['possible_relics'] if r not in self.relics]
        chosen = []
        if offers and offers[0]:
            keys, probs = list(offers[0]), np.array(offers[1])
            while len(chosen) < 3 and keys:
                pick = keys[self.rng.choice(len(keys), p=probs / probs.sum())]
                idx = keys.index(pick); keys.pop(idx); probs = np.delete(probs, idx)
                if pick not in self.relics:
                    chosen.append(pick)
        while len(chosen) < 3 and possible:
            pick = possible[int(self.rng.integers(len(possible)))]
            possible.remove(pick)
            if pick not in chosen:
                chosen.append(pick)
        self.phase, self.options = 'ancient', chosen
        self._floor_start()

    def _floor_start(self):
        self._hp_before, self._gold_before = self.hp, self.gold
        self._floor_info = {'gold_gained': 0, 'gold_spent': 0, 'damage_taken': 0, 'hp_healed': 0, 'max_hp_gained': 0,
                            'max_hp_lost': 0, 'cards_gained': [], 'cards_removed': [], 'upgraded': [], 'relics_gained': [],
                            'card_options': None, 'card_option_ids': None, 'card_picked': None, 'rest_choices': None,
                            'relic_options': None, 'ancient_options': None, 'ancient_choice': None, 'encounter': None,
                            'event': None, 'room_types': [], 'node_type': None, 'combat': None}

    def _floor_end(self):
        if not self.record_history:
            return
        info = self._floor_info
        self.history.append({
            'run': None, 'act_index': self.act_index, 'act_id': self.act_id, 'floor': self.floor,
            'node_type': info['node_type'], 'room_types': info['room_types'], 'encounter': info['encounter'],
            'event': info['event'], 'hp_before': self._hp_before, 'hp_after': self.hp, 'max_hp_after': self.max_hp,
            'gold_before': self._gold_before, 'gold_after': self.gold,
            'gold_gained': info['gold_gained'], 'gold_spent': info['gold_spent'], 'gold_lost': 0,
            'damage_taken': info['damage_taken'], 'hp_healed': info['hp_healed'],
            'max_hp_gained': info['max_hp_gained'], 'max_hp_lost': info['max_hp_lost'],
            'card_options': info['card_options'], 'card_option_ids': info['card_option_ids'], 'card_picked': info['card_picked'],
            'rest_choices': info['rest_choices'], 'upgraded': info['upgraded'], 'cards_gained': info['cards_gained'],
            'cards_removed': info['cards_removed'], 'cards_transformed': 0, 'cards_enchanted': 0,
            'relics_gained': info['relics_gained'], 'relic_options': info['relic_options'],
            'ancient_options': info['ancient_options'], 'ancient_choice': info['ancient_choice'],
            'deck_size_after': len(self.deck), 'relic_count_after': len(self.relics), 'potions_used': 0,
            'final': self.done, 'win': self.won, 'abandoned': False, 'combat': info['combat'],
        })

    # ------------------------------------------------------------------ state changes
    def _gain_gold(self, amount):
        amount = int(amount)
        self.gold = max(0, self.gold + amount)
        if amount >= 0:
            self._floor_info['gold_gained'] += amount
        else:
            self._floor_info['gold_spent'] += -amount

    def _change_hp(self, delta, *, allow_death=False):
        delta = int(delta)
        before = self.hp
        self.hp = min(self.max_hp, self.hp + delta)
        if not allow_death:
            self.hp = max(1, self.hp)
        if self.hp < before:
            self._floor_info['damage_taken'] += before - self.hp
        elif self.hp > before:
            self._floor_info['hp_healed'] += self.hp - before

    def _change_max_hp(self, delta):
        delta = int(delta)
        if delta == 0:
            return
        self.max_hp = max(1, self.max_hp + delta)
        if delta > 0:
            self._floor_info['max_hp_gained'] += delta
            self.hp = min(self.max_hp, self.hp + delta)
        else:
            self._floor_info['max_hp_lost'] += -delta
            self.hp = min(self.hp, self.max_hp)

    def _add_card(self, card_id, upgrade=0):
        if card_id not in self.card_info:
            return
        state = ()
        if card_id == 'MAD_SCIENCE':   # Tinker Time: type 1-3 with a matching rider
            kind = int(self.rng.integers(1, 4))
            state = (('TinkerTimeRider', int(self.rng.integers(3 * kind - 2, 3 * kind + 1))), ('TinkerTimeType', kind))
        self.deck.append(CardInstance(card_id, upgrade, state))
        self._floor_info['cards_gained'].append(card_id)

    def _remove_card(self, index):
        card = self.deck.pop(index)
        self._floor_info['cards_removed'].append(card.id)

    def _auto_remove(self, n):
        """Rule-based removal used for relic/event effects: curses, then basics, then random."""
        for _ in range(n):
            if len(self.deck) <= 1:
                return
            order = sorted(range(len(self.deck)), key=lambda i: (
                0 if self.card_info.get(self.deck[i].id, {}).get('type') == 'Curse' else
                1 if self.deck[i].id in BASIC_CARDS else 2, self.rng.random()))
            self._remove_card(order[0])

    def _upgrade(self, index):
        card = self.deck[index]
        card.upgrade = min(card.upgrade + 1, self.card_info.get(card.id, {}).get('max_upgrade_level', 1))
        self._floor_info['upgraded'].append(card.id)

    def _auto_upgrade(self, n):
        candidates = [i for i, c in enumerate(self.deck) if self._upgradable(c) and c.id not in BASIC_CARDS]
        candidates = candidates or [i for i, c in enumerate(self.deck) if self._upgradable(c)]
        for i in self.rng.permutation(candidates)[:n]:
            self._upgrade(int(i))

    def _upgradable(self, card):
        info = self.card_info.get(card.id)
        return bool(info) and info['type'] not in ('Curse', 'Status') and card.upgrade < info['max_upgrade_level']

    def _add_relic(self, relic_id, apply_effect=True):
        if relic_id in self.relics or relic_id not in self.relic_info:
            return False
        self.relics.append(relic_id)
        self.relic_states[relic_id] = self._sample_relic_state(relic_id)
        self._floor_info['relics_gained'].append(relic_id)
        if apply_effect:
            effects = self.tables['relic_effects'].get(relic_id)
            if effects:
                e = effects[int(self.rng.integers(len(effects)))]
                self._change_max_hp(e['dmax'])
                self._change_hp(e['dhp'] - max(0, e['dmax']))
                self._gain_gold(e['dgold'])
                for c in e['cards']:
                    self._add_card(c)
                self._auto_remove(e['removed'])
                self._auto_upgrade(e['upgraded'])
            elif relic_id in self._relic_max_hp:
                self._change_max_hp(self._choice(self._relic_max_hp[relic_id]))
        return True

    # ------------------------------------------------------------------ rooms
    def _enter_node(self, node_id):
        node = self.map.nodes[node_id]
        self.node = node_id
        self.floor += 1
        self.total_floor += 1
        self._floor_start()
        self._floor_info['node_type'] = node.type
        room = node.type
        if room == 'unknown':
            resolved = self._choice(self._unknown[self.act_id]) or 'event'
            room = {'event+monster': 'monster', 'event+elite': 'elite'}.get(resolved, resolved)
        self._floor_info['room_types'] = [room]
        if room in ('monster', 'elite', 'boss'):
            self._start_combat(room)
        elif room == 'shop':
            self._open_shop()
        elif room == 'rest_site':
            self.phase, self.options = 'rest', ['heal'] + [i for i, c in enumerate(self.deck) if self._upgradable(c)]
        elif room == 'treasure':
            relic = self._sample_relic(self._relic_rarity['treasure'])
            self._floor_info['relic_options'] = [relic] if relic else []
            if relic:
                self._add_relic(relic)
            self._gain_gold(self._choice(self._gold[self.act_id].get('treasure', ([0], np.array([1.0])))) or 0)
            self._after_room()
        elif room == 'event':
            self._run_event()
            self._after_room()
        else:
            raise ValueError(f'Unknown room type {room}')

    def _run_event(self):
        event = self._choice(self._events.get(self.act_id, ([], np.array([]))))
        self._floor_info['event'] = event
        if event is None:
            return
        outcomes = self.tables['event_outcomes'][event]
        o = outcomes[int(self.rng.integers(len(outcomes)))]
        self._change_max_hp(o['dmax'])
        self._change_hp(o['dhp'] - max(0, o['dmax']))
        self._gain_gold(o['dgold'])
        for c in o['cards']:
            self._add_card(c)
        self._auto_remove(o['removed'])
        self._auto_upgrade(o['upgraded'])
        if o.get('transformed'):
            self._auto_remove(o['transformed'])
            for c in self._sample_cards(self._card_rarity_table('monster'), o['transformed']):
                self._add_card(c)
        for r in o['relics']:
            self._add_relic(r)

    def _start_combat(self, room):
        if room == 'boss':
            for _attempt in range(10):
                enc = self._sample_encounter('boss')
                if enc not in self.boss_encounters:
                    break
            self.boss_encounters.append(enc)
        elif room == 'elite':
            enc = self._sample_encounter('elite')
        else:
            kind = 'weak' if self.fights_in_act < self.tables['weak_fights'].get(self.act_id, 0) else 'normal'
            enc = self._sample_encounter(kind) or self._sample_encounter('normal')
            self.fights_in_act += 1
        self.last_encounter = enc
        self._floor_info['encounter'] = enc
        self._combat_room = room
        self.pending_combat = CombatRequest(self.build(), enc, self.hp, self.max_hp, room)
        self.phase, self.options = 'combat', []
        if self.oracle is not None:
            self.resolve_combat(self.oracle.resolve([self.pending_combat])[0])

    def resolve_combat(self, result: CombatResult):
        assert self.phase == 'combat' and self.pending_combat is not None
        room = self._combat_room
        self.pending_combat = None
        self._floor_info['combat'] = {'expected_loss': result.expected_loss, 'death_probability': result.death_probability,
                                      'spread': result.spread, 'untrained': result.untrained}
        loss = min(self.hp, max(0, int(result.hp_loss)))
        self._change_hp(-loss, allow_death=True)
        if result.died or self.hp <= 0:
            self.hp = 0
            self._finish(won=False)
            return
        gold_table = self._gold[self.act_id].get(room)
        if room == 'boss':
            if self.act < 3:
                self._gain_gold(self.structure['boss_gold'])
            self.boss_fights_done += 1
        elif gold_table:
            self._gain_gold(self._choice(gold_table) or 0)
        if room == 'elite':
            relic = self._sample_relic(self._relic_rarity['elite'])
            self._floor_info['relic_options'] = [relic] if relic else []
            if relic:
                self._add_relic(relic)
        if room == 'boss' and f'{self.act_id}:boss' not in self._card_rarity:
            # Final-act bosses grant no card reward in the histories.
            self._after_room()
            return
        options = self._sample_cards(self._card_rarity_table(room), 3)
        self._floor_info['card_options'], self._floor_info['card_option_ids'] = len(options), list(options)
        self.phase, self.options = 'card_reward', options

    def _open_shop(self):
        n = self._choice(self._shop_n) or 6
        stock = ShopStock(purge_price=self.structure['purge_base_cost'] + self.structure['purge_cost_step'] * self.purges)
        seen = set()
        for _ in range(n):
            mix = self._choice(self._shop_mix)
            pool, rarity = mix.split(':')
            cards = [c for c in self.tables['pools']['silent' if pool == 'SILENT' else 'colorless'].get(rarity, []) if c not in seen]
            if not cards:
                continue
            card = cards[int(self.rng.integers(len(cards)))]
            seen.add(card)
            price = self._prices[f'card:{pool}:{rarity}']
            stock.cards.append({'id': card, 'price': int(round(price * self.rng.uniform(0.95, 1.05)))})
        if stock.cards:
            sale = int(self.rng.integers(len(stock.cards)))
            stock.cards[sale]['price'] = int(round(stock.cards[sale]['price'] * self.structure['shop_sale_fraction']))
        for _ in range(3):
            relic = self._sample_relic(self._shop_relic_rarity, allow_shop=True)
            if relic and relic not in {r['id'] for r in stock.relics}:
                rarity = self.relic_info[relic]['rarity']
                stock.relics.append({'id': relic, 'price': int(round(self._prices[f'relic:{rarity}'] * self.rng.uniform(0.95, 1.05)))})
        self.shop = stock
        self._floor_info['card_options'] = len(stock.cards)
        self._floor_info['card_option_ids'] = [c['id'] for c in stock.cards]
        self._floor_info['card_picked'] = False
        self._floor_info['relic_options'] = [r['id'] for r in stock.relics]
        self.phase = 'shop'
        self._refresh_shop_options()

    def _refresh_shop_options(self):
        opts = [('leave',)]
        opts += [('buy_card', i) for i, c in enumerate(self.shop.cards) if c['price'] <= self.gold]
        opts += [('buy_relic', i) for i, r in enumerate(self.shop.relics) if r['price'] <= self.gold]
        if self.shop.purge_price <= self.gold and len(self.deck) > 1:
            opts += [('purge', i) for i in range(len(self.deck))]
        self.options = opts

    def _after_room(self):
        """Close the current floor and move on: map choice, next act or victory."""
        node = self.map.nodes[self.node]
        if node.type == 'boss':
            if self.boss_fights_done < self.act_spec['boss_fights']:
                self._floor_end()
                self._floor_start()
                self.floor += 1; self.total_floor += 1
                self._floor_info['node_type'] = 'boss'; self._floor_info['room_types'] = ['boss']
                self._start_combat('boss')
                return
            if self.act_index == 2:
                self._finish(won=True)
                return
            self._floor_end()
            self._begin_act()
            return
        self._floor_end()
        self.phase, self.options = 'map', list(node.children)

    def _finish(self, won):
        self.done, self.won = True, won
        self.phase, self.options = 'done', []
        self._floor_end()

    # ------------------------------------------------------------------ public API
    def build(self) -> Build:
        cards = tuple(Card(c.id, c.upgrade, persistent_state=c.state) for c in self.deck if c.id in self.allowed_cards)
        relics = tuple(Relic(r, self.relic_states[r]) for r in self.relics if r in self.allowed_relics)
        return Build(self.act_id, self.act, cards, relics, tuple(self.ancient_history), family='sim')

    def legal_actions(self):
        if self.phase == 'ancient':
            return [('relic', r) for r in self.options]
        if self.phase == 'map':
            return [('go', n) for n in self.options]
        if self.phase == 'card_reward':
            return [('card', i) for i in range(len(self.options))] + [('skip',)]
        if self.phase == 'rest':
            return [('heal',)] + [('smith', i) for i in self.options if i != 'heal']
        if self.phase == 'shop':
            return list(self.options)
        return []

    def observation(self):
        node = self.map.nodes[self.node] if self.node is not None else None
        obs = {'phase': self.phase, 'act_index': self.act_index, 'act_id': self.act_id, 'act': self.act,
               'floor': self.floor, 'total_floor': self.total_floor, 'hp': self.hp, 'max_hp': self.max_hp, 'gold': self.gold,
               'deck': [(c.id, c.upgrade) for c in self.deck], 'relics': list(self.relics),
               'fights_in_act': self.fights_in_act, 'rows': self.map.rows,
               'node': {'id': node.id, 'row': node.row, 'type': node.type} if node else None,
               'done': self.done, 'won': self.won}
        if self.phase == 'map':
            obs['options'] = [{'id': n, 'type': self.map.nodes[n].type, 'row': self.map.nodes[n].row} for n in self.options]
        elif self.phase in ('ancient', 'card_reward'):
            obs['options'] = list(self.options)
        elif self.phase == 'rest':
            obs['options'] = {'heal': math.floor(self.structure['rest_heal_ratio'] * self.max_hp),
                              'smith': [i for i in self.options if i != 'heal']}
        elif self.phase == 'shop':
            obs['shop'] = {'cards': list(self.shop.cards), 'relics': list(self.shop.relics), 'purge_price': self.shop.purge_price}
        return obs

    def step(self, action):
        if self.done:
            raise RuntimeError('Episode is over')
        if self.phase == 'combat':
            raise RuntimeError('Combat pending; resolve it through the oracle first')
        kind = action[0]
        if self.phase == 'ancient':
            assert kind == 'relic' and action[1] in self.options, action
            self._floor_info['node_type'], self._floor_info['room_types'], self._floor_info['event'] = 'ancient', ['event'], self.ancient
            self._floor_info['ancient_options'], self._floor_info['ancient_choice'] = list(self.options), action[1]
            self._floor_info['relic_options'] = list(self.options)
            self.ancient_history.append((self.act, self.ancient, action[1]))
            self._add_relic(action[1])
            self._floor_end()
            self.phase, self.options = 'map', list(self.map.starts)
        elif self.phase == 'map':
            assert kind == 'go' and action[1] in self.options, action
            self._enter_node(action[1])
        elif self.phase == 'card_reward':
            if kind == 'card':
                self._add_card(self.options[action[1]])
                self._floor_info['card_picked'] = True
            else:
                assert kind == 'skip', action
                self._floor_info['card_picked'] = False
            self._after_room()
        elif self.phase == 'rest':
            if kind == 'heal':
                self._floor_info['rest_choices'] = ['HEAL']
                self._change_hp(math.floor(self.structure['rest_heal_ratio'] * self.max_hp))
            else:
                assert kind == 'smith' and action[1] in self.options, action
                self._floor_info['rest_choices'] = ['SMITH']
                self._upgrade(action[1])
            self._after_room()
        elif self.phase == 'shop':
            assert action in self.options, (action, self.options[:5])
            if kind == 'leave':
                self.shop = None
                self._after_room()
            else:
                if kind == 'buy_card':
                    item = self.shop.cards.pop(action[1])
                    self._gain_gold(-item['price'])
                    self._add_card(item['id'])
                    self._floor_info['card_picked'] = True
                elif kind == 'buy_relic':
                    item = self.shop.relics.pop(action[1])
                    self._gain_gold(-item['price'])
                    self._add_relic(item['id'])
                elif kind == 'purge':
                    self._gain_gold(-self.shop.purge_price)
                    self._remove_card(action[1])
                    self.purges += 1
                    self.shop.purge_price += self.structure['purge_cost_step']
                self._refresh_shop_options()
        else:
            raise RuntimeError(f'No action expected in phase {self.phase}')
        reward = 1.0 if (self.done and self.won) else 0.0
        return self.observation(), reward, self.done, {'phase': self.phase, 'floor': self.total_floor}


class VecRunEnv:
    """Steps many envs with one policy and resolves their combats in one oracle batch."""

    def __init__(self, envs: list[RunEnv], oracle: CombatOracle):
        self.envs, self.oracle = envs, oracle
        for env in envs:
            env.oracle = None

    def run(self, policy, max_steps=10_000):
        active = [e for e in self.envs if not e.done]
        for _ in range(max_steps):
            pending = [e for e in active if e.phase == 'combat']
            if pending:
                results = self.oracle.resolve([e.pending_combat for e in pending])
                for env, result in zip(pending, results):
                    env.resolve_combat(result)
            active = [e for e in self.envs if not e.done]
            if not active:
                return
            for env in active:
                if env.phase not in ('combat', 'done'):
                    env.step(policy.act(env))
        raise RuntimeError('VecRunEnv.run did not converge')
