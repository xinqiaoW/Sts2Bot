"""Baseline out-of-combat policies used for calibration rollouts.

``RandomPolicy`` picks uniformly among legal actions. ``HeuristicPolicy`` is a
small rule set that mimics common human tendencies (rest when low, take most
card rewards, buy removals) so that trajectory statistics are compared against
a plausible rather than a degenerate path through the map. Neither looks at
the combat model.
"""
from __future__ import annotations

import numpy as np

from .env import BASIC_CARDS, RunEnv


class Policy:
    name = 'policy'

    def act(self, env: RunEnv):
        raise NotImplementedError


class RandomPolicy(Policy):
    name = 'random'

    def __init__(self, seed=0):
        self.rng = np.random.default_rng(seed)

    def act(self, env):
        actions = env.legal_actions()
        return actions[int(self.rng.integers(len(actions)))]


class HeuristicPolicy(Policy):
    name = 'heuristic'

    def __init__(self, seed=0, card_pick_rate=None):
        self.rng = np.random.default_rng(seed)
        self.card_pick_rate = card_pick_rate or {'monster': 0.78, 'elite': 0.73, 'boss': 0.92}

    def act(self, env):
        phase = env.phase
        rng = self.rng
        if phase == 'ancient':
            return ('relic', env.options[int(rng.integers(len(env.options)))])
        if phase == 'map':
            hp_ratio = env.hp / env.max_hp
            options = [(n, env.map.nodes[n].type) for n in env.options]
            prefer = []
            if hp_ratio < 0.5:
                prefer = ['rest_site', 'shop', 'unknown', 'monster', 'treasure', 'elite']
            elif hp_ratio > 0.7:
                prefer = ['elite', 'treasure', 'rest_site', 'unknown', 'monster', 'shop']
            else:
                prefer = ['treasure', 'unknown', 'monster', 'rest_site', 'shop', 'elite']
            rank = {t: i for i, t in enumerate(prefer)}
            best = min(rank.get(t, 9) for _, t in options)
            pick = [n for n, t in options if rank.get(t, 9) == best]
            return ('go', pick[int(rng.integers(len(pick)))])
        if phase == 'card_reward':
            room = env._combat_room
            if rng.random() < self.card_pick_rate.get(room, 0.78) and env.options:
                return ('card', int(rng.integers(len(env.options))))
            return ('skip',)
        if phase == 'rest':
            smith = [i for i in env.options if i != 'heal' and env.deck[i].id not in BASIC_CARDS]
            smith = smith or [i for i in env.options if i != 'heal']
            if env.hp / env.max_hp < 0.6 or not smith:
                return ('heal',)
            return ('smith', smith[int(rng.integers(len(smith)))])
        if phase == 'shop':
            actions = env.legal_actions()
            purges = [a for a in actions if a[0] == 'purge' and (env.deck[a[1]].id in BASIC_CARDS
                      or env.card_info.get(env.deck[a[1]].id, {}).get('type') == 'Curse')]
            if purges and rng.random() < 0.4:
                return purges[int(rng.integers(len(purges)))]
            relics = [a for a in actions if a[0] == 'buy_relic' and env.shop.relics[a[1]]['price'] <= env.gold]
            if relics and rng.random() < 0.7:
                return relics[int(rng.integers(len(relics)))]
            cards = [a for a in actions if a[0] == 'buy_card' and env.shop.cards[a[1]]['price'] <= env.gold]
            if cards and rng.random() < 0.6:
                return cards[int(rng.integers(len(cards)))]
            return ('leave',)
        raise RuntimeError(phase)


class GreedyFPolicy(HeuristicPolicy):
    """Heuristic policy whose deck decisions (card reward, smith target, ancient relic)
    are made by one-step lookahead with the combat model: pick the option minimising
    F's expected loss (+70 x death probability) averaged over the act's elite and boss
    pool. Map and shop choices stay heuristic. It is the simplest F-aware baseline and
    shows how much of the F arm's early collapse is deck quality rather than oracle bias."""
    name = 'greedy_f'

    def __init__(self, oracle, seed=0, max_candidates=8):
        super().__init__(seed)
        self.oracle = oracle
        self.max_candidates = max_candidates

    def _targets(self, env):
        pools = env._pools[env.act_id]
        targets = [t for t in list(pools['elite'][0]) + list(pools['boss'][0]) if self.oracle.covers(env.act_id, t)]
        return targets or [t for t in pools['normal'][0] if self.oracle.covers(env.act_id, t)]

    def _score(self, env, variants):
        """``variants``: list of (cards, relics) tuples. Returns one score per variant (lower is better)."""
        from damage_model.schema import Build
        from .oracle import CombatRequest
        targets = self._targets(env)
        if not targets:
            return np.zeros(len(variants))
        requests = [CombatRequest(Build(env.act_id, env.act, cards, relics, tuple(env.ancient_history), family='sim'), t, env.hp, env.max_hp, 'elite')
                    for cards, relics in variants for t in targets]
        mean, _std, death, _ = self.oracle.predict(requests)
        return (mean + 70.0 * death).reshape(len(variants), len(targets)).mean(1)

    def act(self, env):
        from damage_model.schema import Card, Relic
        phase = env.phase
        if phase == 'card_reward' and env.options:
            base = env.build()
            variants = [(base.cards, base.relics)]
            for opt in env.options:
                extra = (Card(opt),) if opt in env.allowed_cards else ()
                variants.append((base.cards + extra, base.relics))
            scores = self._score(env, variants)
            best = int(np.argmin(scores))
            return ('skip',) if best == 0 else ('card', best - 1)
        if phase == 'rest':
            if env.hp / env.max_hp < 0.5:
                return ('heal',)
            smith = [i for i in env.options if i != 'heal']
            if not smith:
                return ('heal',)
            if len(smith) > self.max_candidates:
                smith = [int(i) for i in self.rng.choice(smith, self.max_candidates, replace=False)]
            base = env.build()
            variants = [(base.cards, base.relics)]
            for i in smith:
                cards = list(env.deck)
                cards[i] = type(cards[i])(cards[i].id, cards[i].upgrade + 1, cards[i].state)
                variants.append((tuple(Card(c.id, c.upgrade, persistent_state=c.state) for c in cards if c.id in env.allowed_cards), base.relics))
            scores = self._score(env, variants)
            best = int(np.argmin(scores))
            return ('heal',) if best == 0 else ('smith', smith[best - 1])
        if phase == 'ancient':
            base = env.build()
            variants = []
            for relic in env.options:
                extra = (Relic(relic, env._sample_relic_state(relic)),) if relic in env.allowed_relics else ()
                variants.append((base.cards, base.relics + extra))
            scores = self._score(env, variants)
            return ('relic', env.options[int(np.argmin(scores))])
        return super().act(env)
