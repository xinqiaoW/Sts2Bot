"""Fit the simulator's empirical rule tables from human ``.run`` histories.

Everything the simulator cannot read from the game catalog (map row structure,
encounter pool ordering, reward odds, gold amounts, shop stock and prices,
event outcomes, ancient offers and relic pickup effects) is estimated here from
the *fit* split of Spire Codex runs and written to one JSON file. Structural
constants that were verified against the histories but are not fitted (start
HP/gold, rest heal ratio, inter-act heal) live in ``STRUCTURE`` with a note on
how they were checked.

Usage::

    python -m sim.tables --output data/sim/tables-v0.json
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path

from damage_model.catalog import Catalog

from . import ROOT
from .history import START_GOLD, START_HP, START_MAX_HP, all_floor_records, load_runs, split_runs

TABLES_VERSION = 'sim-tables-v0'
DEFAULT_OUTPUT = ROOT / 'data/sim/tables-v0.json'
ROOM_TYPES = ('monster', 'elite', 'rest_site', 'shop', 'unknown', 'treasure')

# Verified against the histories (see docstrings in sim.calibrate for the checks).
STRUCTURE = {
    'start': {'hp': START_HP, 'max_hp': START_MAX_HP, 'gold': START_GOLD},
    # rows = map rows before the boss (floor index 1..rows); floor 0 is the ancient.
    'acts': {
        'OVERGROWTH': {'act': 1, 'rows': 15, 'treasure_row': 9, 'boss_fights': 1},
        'UNDERDOCKS': {'act': 1, 'rows': 15, 'treasure_row': 9, 'boss_fights': 1},
        'HIVE': {'act': 2, 'rows': 14, 'treasure_row': 8, 'boss_fights': 1},
        'GLORY': {'act': 3, 'rows': 13, 'treasure_row': 7, 'boss_fights': 2},
    },
    # First row is always a monster, elites/rest sites appear from row 6, the last
    # row is always a rest site and the two rows before it never are.
    'first_elite_row': 6,
    'rest_heal_ratio': 0.30,          # HEAL heals 30% of max HP (14,135 rest floors, median 0.30)
    'inter_act_heal_ratio': 0.80,     # entering act 2/3 heals floor(0.8 * missing HP)
    'boss_gold': 75,
    'purge_base_cost': 100, 'purge_cost_step': 50,
    'shop_sale_fraction': 0.5,        # one card per shop at half price (25 vs 48-52 observed)
    # Map generator: ``fitted_rows`` uses the per-floor mix of node types humans visited
    # (``row_types``) as generation weights; ``static`` uses the STS1-like weights below.
    # The true generated mix is not observable from visited-only histories.
    'map_generator': {
        'mode': 'fitted_rows', 'width': 7, 'paths': 6,
        'early_rows': {'monster': 0.55, 'unknown': 0.33, 'shop': 0.12},
        'late_rows': {'monster': 0.40, 'elite': 0.14, 'rest_site': 0.16, 'unknown': 0.24, 'shop': 0.06},
    },
}


def _hist(counter: Counter):
    return {str(k): int(v) for k, v in sorted(counter.items(), key=lambda kv: str(kv[0]))}


def plausible(outcome: dict) -> bool:
    """Reject glitched floor deltas (e.g. one recorded +9640 gold event) before they
    become samplable outcomes."""
    return (abs(outcome['dhp']) <= 80 and abs(outcome['dmax']) <= 40 and -400 <= outcome['dgold'] <= 400
            and len(outcome['cards']) <= 6 and outcome['removed'] <= 6 and outcome['upgraded'] <= 10)


def fit_tables(runs: dict, catalog: Catalog, log=print) -> dict:
    records = all_floor_records(runs)
    cards, relics = catalog.cards, catalog.relics
    act1 = Counter()
    row_types = defaultdict(Counter)
    unknown = defaultdict(Counter)
    encounters = defaultdict(Counter)
    weak_by_index = defaultdict(Counter)
    gold = defaultdict(Counter)
    card_n = defaultdict(Counter)
    card_rarity = defaultdict(Counter)
    card_pick_rate = defaultdict(Counter)
    shop_n = Counter(); shop_mix = Counter(); shop_relic_rarity = Counter()
    prices = defaultdict(Counter); purge = Counter()
    relic_rarity = defaultdict(Counter)
    ancients = defaultdict(Counter); ancient_offers = defaultdict(Counter); ancient_pick = defaultdict(Counter)
    relic_effects = defaultdict(list); relic_max_hp = defaultdict(Counter)
    events = defaultdict(Counter); event_outcomes = defaultdict(list)
    human_damage = defaultdict(Counter)
    rest_choice = Counter()
    by_run = defaultdict(list)
    for r in records:
        by_run[r['run']].append(r)
    for run_records in by_run.values():
        act1[run_records[0]['act_id']] += 1
        fights = Counter()
        for r in run_records:
            act, t = r['act_id'], r['node_type']
            row_types[act][(r['floor'], t)] += 1
            if t == 'unknown':
                unknown[act]['+'.join(r['room_types'])] += 1
            enc = r['encounter']
            if enc and enc in {e['id'] for e in catalog.acts.get(act, {}).get('encounters', [])}:
                rt = r['room_types'][0]
                encounters[act][(rt, enc)] += 1
                if rt == 'monster':
                    weak_by_index[act][(fights[act], enc.endswith('_WEAK'))] += 1
                    fights[act] += 1
                human_damage[enc][r['damage_taken']] += 1
            if t in ('monster', 'elite', 'boss', 'treasure') and not r['final']:
                gold[act][(t, r['gold_gained'])] += 1
            if r['card_options'] and t in ('monster', 'elite', 'boss'):
                card_n[t][r['card_options']] += 1
                card_pick_rate[t][bool(r['card_picked'])] += 1
                for cid in r['card_option_ids']:
                    c = cards.get(cid)
                    if c and c['pool'] == 'SILENT_CARD_POOL':
                        card_rarity[(act, t)][c['rarity']] += 1
            if t == 'shop':
                if r['card_options'] and r['card_options'] <= 8:
                    shop_n[r['card_options']] += 1
                    for cid in r['card_option_ids']:
                        c = cards.get(cid)
                        if c and c['pool'] in ('SILENT_CARD_POOL', 'COLORLESS_CARD_POOL'):
                            shop_mix[f"{c['pool'].split('_')[0]}:{c['rarity']}"] += 1
                for rid in r['relic_options'] or []:
                    rel = relics.get(rid)
                    if rel:
                        shop_relic_rarity[rel['rarity']] += 1
                bought = list(r['cards_gained']) + list(r['relics_gained'])
                if r['gold_spent'] > 0 and len(bought) + len(r['cards_removed']) == 1:
                    if r['cards_removed']:
                        purge[r['gold_spent']] += 1
                    elif bought[0] in cards:
                        c = cards[bought[0]]
                        prices[f"card:{c['pool'].split('_')[0]}:{c['rarity']}"][r['gold_spent']] += 1
                    elif bought[0] in relics:
                        prices[f"relic:{relics[bought[0]]['rarity']}"][r['gold_spent']] += 1
            if t in ('elite', 'treasure') and r['relic_options']:
                for rid in r['relic_options']:
                    rel = relics.get(rid)
                    if rel and rel['rarity'] in ('Common', 'Uncommon', 'Rare'):
                        relic_rarity[t][rel['rarity']] += 1
            if t == 'rest_site' and r['rest_choices']:
                rest_choice[r['rest_choices'][0]] += 1
            if t == 'ancient' and r['event'] and r['ancient_options'] and len(r['ancient_options']) == 3:
                ancients[act][r['event']] += 1
                for rid in r['ancient_options']:
                    ancient_offers[r['event']][rid] += 1
                if r['ancient_choice']:
                    ancient_pick[r['event']][r['ancient_choice']] += 1
            # Relic pickup effects: floors where exactly one relic was gained and no
            # combat/event confounds the deltas (ancient and treasure floors).
            if t in ('ancient', 'treasure') and len(r['relics_gained']) == 1 and r['hp_after'] > 0:
                hp_before = r['hp_before']
                if t == 'ancient' and r['act_index'] > 0:
                    # Entering act 2/3 heals floor(0.8 * missing HP) before the ancient.
                    prev_max = r['max_hp_after'] - r['max_hp_gained'] + r['max_hp_lost']
                    hp_before += int(STRUCTURE['inter_act_heal_ratio'] * (prev_max - hp_before))
                effect = {
                    'dhp': r['hp_after'] - hp_before, 'dmax': r['max_hp_gained'] - r['max_hp_lost'],
                    'dgold': r['gold_after'] - r['gold_before'] if t == 'ancient' else 0,
                    'cards': list(r['cards_gained']), 'removed': len(r['cards_removed']),
                    'upgraded': len(r['upgraded'])}
                if plausible(effect):
                    relic_effects[r['relics_gained'][0]].append(effect)
            if t in ('elite', 'boss', 'monster') and len(r['relics_gained']) == 1 and (r['max_hp_gained'] or r['max_hp_lost']):
                relic_max_hp[r['relics_gained'][0]][r['max_hp_gained'] - r['max_hp_lost']] += 1
            if t == 'unknown' and r['room_types'] == ['event'] and r['event'] and r['hp_after'] > 0:
                outcome = {
                    'dhp': r['hp_after'] - r['hp_before'], 'dmax': r['max_hp_gained'] - r['max_hp_lost'],
                    'dgold': r['gold_after'] - r['gold_before'],
                    'cards': list(r['cards_gained']), 'removed': len(r['cards_removed']),
                    'upgraded': len(r['upgraded']), 'transformed': r['cards_transformed'],
                    'relics': list(r['relics_gained'])}
                if plausible(outcome):
                    events[act][r['event']] += 1
                    event_outcomes[r['event']].append(outcome)
    # Catalog-derived pools.
    silent_pool = defaultdict(list)
    colorless_pool = defaultdict(list)
    for c in catalog.raw['cards']:
        if c['multiplayer_constraint'] == 'MultiplayerOnly' or c['id'] in catalog.excluded['cards']:
            continue
        if c['pool'] == 'SILENT_CARD_POOL' and c['rarity'] in ('Common', 'Uncommon', 'Rare'):
            silent_pool[c['rarity']].append(c['id'])
        if c['pool'] == 'COLORLESS_CARD_POOL' and c['rarity'] in ('Uncommon', 'Rare'):
            colorless_pool[c['rarity']].append(c['id'])
    relic_pool = defaultdict(list)
    for rel in catalog.raw['relics']:
        if rel['pool'] in ('SHARED_RELIC_POOL', 'SILENT_RELIC_POOL') and rel['rarity'] in ('Common', 'Uncommon', 'Rare', 'Shop'):
            relic_pool[rel['rarity']].append(rel['id'])
    # Weak-fight prefix length per act: the largest fight index that is always weak.
    weak_fights = {}
    for act, counter in weak_by_index.items():
        k = 0
        while counter.get((k, True), 0) > 0 and counter.get((k, False), 0) <= 0.02 * counter.get((k, True), 0):
            k += 1
        weak_fights[act] = k
    tables = {
        'version': TABLES_VERSION, 'fit_runs': len(by_run), 'game_sha256': catalog.raw['game_sha256'],
        'structure': STRUCTURE,
        'act1_choice': _hist(act1),
        'row_types': {act: {f'{floor}:{t}': n for (floor, t), n in sorted(v.items(), key=str)} for act, v in row_types.items()},
        'unknown_resolution': {act: _hist(v) for act, v in unknown.items()},
        'encounters': {act: {f'{rt}:{enc}': n for (rt, enc), n in sorted(v.items())} for act, v in encounters.items()},
        'weak_fights': weak_fights,
        'weak_by_index': {act: {f'{i}:{int(w)}': n for (i, w), n in sorted(v.items())} for act, v in weak_by_index.items()},
        'gold': {act: {f'{t}:{g}': n for (t, g), n in sorted(v.items())} for act, v in gold.items()},
        'card_reward_options': {t: _hist(v) for t, v in card_n.items()},
        'card_reward_rarity': {f'{act}:{t}': _hist(v) for (act, t), v in card_rarity.items()},
        'card_pick_rate': {t: _hist(v) for t, v in card_pick_rate.items()},
        'shop': {'n_cards': _hist(shop_n), 'card_mix': _hist(shop_mix), 'relic_rarity': _hist(shop_relic_rarity),
                 'prices': {k: _hist(v) for k, v in prices.items()}, 'purge': _hist(purge)},
        'relic_rarity': {t: _hist(v) for t, v in relic_rarity.items()},
        'rest_choice': _hist(rest_choice),
        'ancients': {act: _hist(v) for act, v in ancients.items()},
        'ancient_offers': {a: _hist(v) for a, v in ancient_offers.items()},
        'ancient_pick': {a: _hist(v) for a, v in ancient_pick.items()},
        'relic_effects': {k: v for k, v in relic_effects.items() if len(v) >= 3},
        'relic_max_hp': {k: _hist(v) for k, v in relic_max_hp.items() if sum(v.values()) >= 3},
        'events': {act: _hist(v) for act, v in events.items()},
        'event_outcomes': {k: v for k, v in event_outcomes.items() if len(v) >= 5},
        'human_damage': {k: _hist(v) for k, v in human_damage.items()},
        'pools': {'silent': dict(silent_pool), 'colorless': dict(colorless_pool), 'relic': dict(relic_pool)},
    }
    log(json.dumps({'event': 'tables_fitted', 'runs': len(by_run), 'floors': len(records),
                    'events': sum(len(v) for v in event_outcomes.values()), 'weak_fights': weak_fights}))
    return tables


def load_tables(path=DEFAULT_OUTPUT) -> dict:
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--output', default=str(DEFAULT_OUTPUT))
    parser.add_argument('--holdout-fraction', type=float, default=0.2)
    parser.add_argument('--catalog', default=str(ROOT / 'catalogs/game-0.111.0.raw.json'))
    parser.add_argument('--config', default=str(ROOT / 'configs/real-runs-8s.json'))
    args = parser.parse_args()
    catalog = Catalog.load(args.catalog, args.config)
    runs = load_runs()
    fit, holdout = split_runs(runs, args.holdout_fraction)
    tables = fit_tables(fit, catalog)
    tables['holdout_runs'] = len(holdout)
    tables['holdout_fraction'] = args.holdout_fraction
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    Path(args.output).write_text(json.dumps(tables, ensure_ascii=False), encoding='utf-8')
    print(json.dumps({'event': 'tables_written', 'path': args.output, 'bytes': Path(args.output).stat().st_size}))


if __name__ == '__main__':
    main()
