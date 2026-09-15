"""Per-floor calibration of the simulator against held-out human runs.

Rolls out the simulator with baseline policies and one or more combat oracles,
summarises human and simulated floor records with the same code, and writes a
deviation report (markdown + JSON) under ``reports/sim/<stamp>/``.

Usage::

    .venv-train/bin/python -m sim.calibrate --episodes 2000 \
        --checkpoint checkpoints/train/<stamp>/set_transformer --checkpoint checkpoints/train/<stamp>/rtdl_resnet

Only the *holdout* split of the human runs is compared (tables are fitted on the
other 80 %), so agreement on fitted quantities is a check of the sampling code
and agreement on emergent quantities (HP/gold trajectories, floors reached, win
rate) is a check of the model.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
import time

import numpy as np

from . import ROOT
from .history import all_floor_records, floor_records, load_runs, split_runs
from .oracle import EmpiricalOracle, ModelOracle
from .policies import GreedyFPolicy, HeuristicPolicy, RandomPolicy
from .rollout import rollout
from .tables import DEFAULT_OUTPUT as DEFAULT_TABLES, load_tables

TRAJECTORY_FLOORS = (1, 3, 6, 9, 12, 16, 17, 20, 25, 30, 33, 34, 38, 42, 46, 48)


# ---------------------------------------------------------------------- summaries
def summarize(records, catalog):
    """Aggregate floor records (human or simulated) into comparable statistics."""
    cards, relics = catalog.cards, catalog.relics
    s = {
        'runs': 0, 'completed_runs': 0, 'wins': 0, 'floors_reached': [], 'death_act': Counter(), 'death_room': Counter(),
        'floor_type': defaultdict(lambda: defaultdict(Counter)), 'unknown': defaultdict(Counter),
        'encounters': defaultdict(lambda: defaultdict(Counter)), 'weak': defaultdict(Counter),
        'gold': defaultdict(lambda: defaultdict(list)), 'shop_spent': [], 'shop_cards': Counter(), 'shop_bought': Counter(),
        'card_options': defaultdict(Counter), 'card_rarity': defaultdict(Counter), 'card_pick': defaultdict(Counter),
        'rest': Counter(), 'heal_ratio': [], 'relic_rarity': defaultdict(Counter),
        'event_freq': defaultdict(Counter), 'event_dhp': defaultdict(list), 'event_dgold': defaultdict(list),
        'damage': defaultdict(list), 'death_rate': defaultdict(list), 'combat_expected': defaultdict(list),
        'traj': defaultdict(lambda: defaultdict(list)), 'hp_before_combat': defaultdict(list),
        'deck_end_of_act': defaultdict(list), 'relics_end_of_act': defaultdict(list), 'ancient_pick': Counter(),
    }
    by_run = defaultdict(list)
    for r in records:
        by_run[r['run']].append(r)
    for run_records in by_run.values():
        s['runs'] += 1
        abandoned = run_records[-1].get('abandoned', False)
        s['completed_runs'] += not abandoned
        fights = Counter()
        for g, r in enumerate(run_records):
            act, t, rooms = r['act_id'], r['node_type'], r['room_types']
            alive = r['hp_after'] > 0
            if r['final'] and abandoned:
                # Quit runs: the last floor is not an outcome and its HP is unreliable.
                break
            if r['final']:
                s['floors_reached'].append(g)
                if r['win']:
                    s['wins'] += 1
                else:
                    s['death_act'][r['act_index']] += 1
                    s['death_room'][t] += 1
            if t != 'ancient':
                s['floor_type'][act][r['floor']][t] += 1
            if t == 'unknown':
                s['unknown'][act]['+'.join(rooms)] += 1
            if r['encounter']:
                rt = rooms[0]
                s['encounters'][act][rt][r['encounter']] += 1
                if rt == 'monster':
                    s['weak'][act][(fights[act], r['encounter'].endswith('_WEAK'))] += 1
                    fights[act] += 1
                s['damage'][r['encounter']].append(r['damage_taken'])
                s['death_rate'][r['encounter']].append(0 if alive else 1)
                s['hp_before_combat'][act].append(r['hp_before'] / max(1, r['max_hp_after']))
                if r.get('combat') and r['combat'].get('expected_loss') is not None:
                    s['combat_expected'][r['encounter']].append(r['combat']['expected_loss'])
            if alive and t in ('monster', 'elite', 'boss', 'treasure'):
                s['gold'][act][t].append(r['gold_gained'])
            if alive and r['card_options'] and t in ('monster', 'elite', 'boss'):
                s['card_options'][t][r['card_options']] += 1
                s['card_pick'][t][bool(r['card_picked'])] += 1
                for cid in r['card_option_ids']:
                    c = cards.get(cid)
                    if c and c['pool'] == 'SILENT_CARD_POOL':
                        s['card_rarity'][f'{act}:{t}'][c['rarity']] += 1
            if rooms == ['shop'] and alive:
                s['shop_spent'].append(r['gold_spent'])
                if r['card_options']:
                    s['shop_cards'][min(r['card_options'], 8)] += 1
                s['shop_bought'][('card', len(r['cards_gained']) > 0)] += 1
                s['shop_bought'][('relic', len(r['relics_gained']) > 0)] += 1
                s['shop_bought'][('purge', len(r['cards_removed']) > 0)] += 1
            if t == 'rest_site' and r['rest_choices']:
                s['rest'][r['rest_choices'][0]] += 1
                if r['rest_choices'][0] == 'HEAL' and r['max_hp_after']:
                    s['heal_ratio'].append(r['hp_healed'] / r['max_hp_after'])
            if t in ('elite', 'treasure') and r['relic_options']:
                for rid in r['relic_options']:
                    rel = relics.get(rid)
                    if rel and rel['rarity'] in ('Common', 'Uncommon', 'Rare'):
                        s['relic_rarity'][t][rel['rarity']] += 1
            if rooms == ['event'] and r['event'] and t == 'unknown':
                s['event_freq'][act][r['event']] += 1
                if alive:
                    s['event_dhp'][r['event']].append(r['hp_after'] - r['hp_before'])
                    s['event_dgold'][r['event']].append(r['gold_after'] - r['gold_before'])
            if t == 'ancient' and r['ancient_choice']:
                s['ancient_pick'][r['ancient_choice']] += 1
            if alive:
                tr = s['traj'][g]
                tr['hp_ratio'].append(r['hp_after'] / max(1, r['max_hp_after']))
                tr['hp'].append(r['hp_after']); tr['max_hp'].append(r['max_hp_after'])
                tr['gold'].append(r['gold_after']); tr['deck'].append(r['deck_size_after']); tr['relics'].append(r['relic_count_after'])
                if t == 'boss' and (g + 1 == len(run_records) or run_records[g + 1]['act_index'] != r['act_index']):
                    s['deck_end_of_act'][r['act_index']].append(r['deck_size_after'])
                    s['relics_end_of_act'][r['act_index']].append(r['relic_count_after'])
    return s


# ---------------------------------------------------------------------- comparison helpers
def tv_distance(a: Counter, b: Counter):
    if not a or not b:
        return None
    ta, tb = sum(a.values()), sum(b.values())
    keys = set(a) | set(b)
    return 0.5 * sum(abs(a.get(k, 0) / ta - b.get(k, 0) / tb) for k in keys)


def dist_row(a: Counter, b: Counter, top=6):
    ta, tb = max(1, sum(a.values())), max(1, sum(b.values()))
    keys = sorted(set(a) | set(b), key=lambda k: -(a.get(k, 0) / ta + b.get(k, 0) / tb))[:top]
    return ', '.join(f'{k}: {100 * a.get(k, 0) / ta:.1f}→{100 * b.get(k, 0) / tb:.1f}' for k in keys)


def num_stats(xs):
    if not xs:
        return None
    xs = np.asarray(xs, dtype=float)
    return {'n': int(len(xs)), 'mean': float(xs.mean()), 'p25': float(np.percentile(xs, 25)),
            'p50': float(np.percentile(xs, 50)), 'p75': float(np.percentile(xs, 75))}


def fmt(x, digits=2):
    return '—' if x is None else (f'{x:.{digits}f}' if isinstance(x, float) else str(x))


def pct(counter: Counter, key):
    total = sum(counter.values())
    return 100 * counter.get(key, 0) / total if total else None


# ---------------------------------------------------------------------- report
def build_report(human, arms: dict, meta: dict, teacher_means: dict | None, human_builds: dict | None = None):
    """``arms`` maps arm name -> summary. Returns (markdown, json_payload)."""
    names = list(arms)
    lines, payload = [], {'meta': meta, 'sections': {}}
    h = human

    def header(title):
        lines.extend(['', f'## {title}', ''])

    def table(cols, rows):
        lines.append('| ' + ' | '.join(cols) + ' |')
        lines.append('|' + '---|' * len(cols))
        for row in rows:
            lines.append('| ' + ' | '.join(str(c) for c in row) + ' |')

    lines.append(f"# Simulator v0 deviation report — {meta['stamp']}")
    lines.append('')
    lines.append(f"Human reference: {h['runs']} held-out Silent A10 runs, of which {h['completed_runs']} were played to the end "
                 f"(the rest were quit early and only contribute floors, not outcomes). Fit split: {meta['fit_runs']} runs, tables `{meta['tables']}`.")
    lines.append('Arms: ' + '; '.join(f"`{n}` = {arms[n]['runs']} episodes ({meta['arms'][n]})" for n in names) + '.')
    lines.append('Cells read `human → arm`; TV = total-variation distance between distributions (0 = identical, 1 = disjoint).')

    # 1. outcomes
    header('1. Run outcomes')
    rows = []
    def outcome_row(label, fn, digits=2):
        rows.append([label, fmt(fn(h), digits)] + [fmt(fn(arms[n]), digits) for n in names])
    outcome_row('completed runs', lambda s: s['completed_runs'])
    outcome_row('win rate %', lambda s: 100 * s['wins'] / max(1, s['completed_runs']), 1)
    outcome_row('floors reached mean', lambda s: num_stats(s['floors_reached'])['mean'] if s['floors_reached'] else None, 1)
    outcome_row('floors reached p25 / p50 / p75', lambda s: '/'.join(f"{v:.0f}" for v in (lambda st: (st['p25'], st['p50'], st['p75']))(num_stats(s['floors_reached']))) if s['floors_reached'] else None)
    for a in range(3):
        outcome_row(f'death in act {a + 1} %', lambda s, a=a: pct(s['death_act'], a), 1)
    for room in ('monster', 'elite', 'boss', 'unknown', 'ancient'):
        outcome_row(f'death room = {room} %', lambda s, room=room: pct(s['death_room'], room), 1)
    table(['metric', 'human'] + names, rows)
    payload['sections']['outcomes'] = {'human': {'win_rate': h['wins'] / max(1, h['completed_runs']), 'floors': num_stats(h['floors_reached'])},
                                       **{n: {'win_rate': arms[n]['wins'] / max(1, arms[n]['completed_runs']), 'floors': num_stats(arms[n]['floors_reached'])} for n in names}}

    # 2. trajectories
    header('2. Trajectories by global floor (survivors only)')
    lines.append('Floor 0 = act-1 ancient, 1–16 act 1 (boss at 16), 17–32 act 2, 33+ act 3.')
    lines.append('')
    for metric, label, digits in (('hp_ratio', 'HP / max HP', 2), ('max_hp', 'max HP', 1), ('gold', 'gold', 0), ('deck', 'deck size', 1), ('relics', 'relic count', 1)):
        rows = []
        for g in TRAJECTORY_FLOORS:
            hv = h['traj'].get(g, {}).get(metric)
            if not hv:
                continue
            hm = statistics.mean(hv)
            row = [g, f'{hm:.{digits}f} (n={len(hv)})']
            for n in names:
                av = arms[n]['traj'].get(g, {}).get(metric)
                row.append(f'{statistics.mean(av):.{digits}f} ({statistics.mean(av) - hm:+.{digits}f}, n={len(av)})' if av else '—')
            rows.append(row)
        lines.append(f'**{label}** (mean; arm cells show value and Δ vs human)')
        lines.append('')
        table(['floor', 'human'] + names, rows)
        lines.append('')
    rows = []
    for a in range(3):
        hv = h['deck_end_of_act'].get(a)
        if hv:
            rows.append([f'deck size after act {a + 1} boss', f'{statistics.mean(hv):.1f}'] +
                        [fmt(statistics.mean(arms[n]['deck_end_of_act'][a]), 1) if arms[n]['deck_end_of_act'].get(a) else '—' for n in names])
            rows.append([f'relics after act {a + 1} boss', f"{statistics.mean(h['relics_end_of_act'][a]):.1f}"] +
                        [fmt(statistics.mean(arms[n]['relics_end_of_act'][a]), 1) if arms[n]['relics_end_of_act'].get(a) else '—' for n in names])
    table(['metric', 'human'] + names, rows)

    # 3. map structure
    header('3. Map structure')
    lines.append('Visited node type per act and floor (TV distance human vs arm; floors with TV ≥ 0.15 listed).')
    lines.append('')
    rows = []
    worst = {}
    for act in ('OVERGROWTH', 'UNDERDOCKS', 'HIVE', 'GLORY'):
        tvs = []
        for floor in sorted(h['floor_type'][act]):
            hc = h['floor_type'][act][floor]
            per_arm = [tv_distance(hc, arms[n]['floor_type'][act].get(floor, Counter())) for n in names]
            tvs.append((floor, per_arm, hc))
        mean_tv = [statistics.mean(t[1][i] for t in tvs if t[1][i] is not None) for i in range(len(names))]
        rows.append([act, 'mean TV over floors'] + [fmt(v, 3) for v in mean_tv])
        for floor, per_arm, hc in tvs:
            if any(v is not None and v >= 0.15 for v in per_arm):
                rows.append([act, f'floor {floor}'] + [fmt(v, 3) for v in per_arm])
                rows.append([act, f'  ↳ {names[0]}', dist_row(hc, arms[names[0]]['floor_type'][act].get(floor, Counter()))] + [''] * (len(names) - 1))
        worst[act] = mean_tv
    table(['act', 'floor', *names], rows)
    lines.append('')
    lines.append('Unknown-room resolution (`?` nodes):')
    lines.append('')
    rows = [[act, fmt(tv_distance(h['unknown'][act], arms[names[0]]['unknown'][act]), 3), dist_row(h['unknown'][act], arms[names[0]]['unknown'][act])]
            for act in ('OVERGROWTH', 'UNDERDOCKS', 'HIVE', 'GLORY')]
    table(['act', f'TV ({names[0]})', f'human → {names[0]}'], rows)
    payload['sections']['map_tv'] = worst

    # 4. encounters
    header('4. Encounter pools')
    rows = []
    for act in ('OVERGROWTH', 'UNDERDOCKS', 'HIVE', 'GLORY'):
        for rt in ('monster', 'elite', 'boss'):
            hc = h['encounters'][act][rt]
            if not hc:
                continue
            rows.append([act, rt] + [fmt(tv_distance(hc, arms[n]['encounters'][act][rt]), 3) for n in names] + [dist_row(hc, arms[names[0]]['encounters'][act][rt], 4)])
    table(['act', 'room', *[f'TV {n}' for n in names], f'human → {names[0]} (top 4)'], rows)
    lines.append('')
    lines.append('Share of `_WEAK` encounters by fight index within the act (human → first arm):')
    lines.append('')
    rows = []
    for act in ('OVERGROWTH', 'UNDERDOCKS', 'HIVE', 'GLORY'):
        cells = []
        for k in range(6):
            hw, hn = h['weak'][act].get((k, True), 0), h['weak'][act].get((k, False), 0)
            aw, an = arms[names[0]]['weak'][act].get((k, True), 0), arms[names[0]]['weak'][act].get((k, False), 0)
            cells.append(f'{100 * hw / max(1, hw + hn):.0f}→{100 * aw / max(1, aw + an):.0f}')
        rows.append([act] + cells)
    table(['act'] + [f'fight {k}' for k in range(6)], rows)

    # 5. rewards
    header('5. Rewards')
    rows = []
    for act in ('OVERGROWTH', 'UNDERDOCKS', 'HIVE', 'GLORY'):
        for rt in ('monster', 'elite', 'boss', 'treasure'):
            hs = num_stats(h['gold'][act][rt])
            if not hs:
                continue
            rows.append([act, rt, f"{hs['mean']:.1f} / {hs['p50']:.0f}"] +
                        [(lambda a: f"{a['mean']:.1f} / {a['p50']:.0f} ({a['mean'] - hs['mean']:+.1f})" if a else '—')(num_stats(arms[n]['gold'][act][rt])) for n in names])
    lines.append('Gold gained per room (mean / median; Δ mean):')
    lines.append('')
    table(['act', 'room', 'human', *names], rows)
    lines.append('')
    rows = []
    for rt in ('monster', 'elite', 'boss'):
        rows.append([f'card options = 3, {rt} %', fmt(pct(h['card_options'][rt], 3), 1)] + [fmt(pct(arms[n]['card_options'][rt], 3), 1) for n in names])
    for rt in ('monster', 'elite', 'boss'):
        rows.append([f'card picked, {rt} %', fmt(pct(h['card_pick'][rt], True), 1)] + [fmt(pct(arms[n]['card_pick'][rt], True), 1) for n in names])
    for key in sorted(h['card_rarity']):
        rows.append([f'card rarity TV {key}', '0'] + [fmt(tv_distance(h['card_rarity'][key], arms[n]['card_rarity'][key]), 3) for n in names])
        rows.append([f'  ↳ {key}', dist_row(h['card_rarity'][key], arms[names[0]]['card_rarity'][key])] + [''] * len(names))
    for rt in ('elite', 'treasure'):
        rows.append([f'relic rarity TV {rt}', '0'] + [fmt(tv_distance(h['relic_rarity'][rt], arms[n]['relic_rarity'][rt]), 3) for n in names])
        rows.append([f'  ↳ {rt}', dist_row(h['relic_rarity'][rt], arms[names[0]]['relic_rarity'][rt])] + [''] * len(names))
    table(['metric', 'human', *names], rows)

    # 6. rest / shop / events
    header('6. Rest sites, shops, events')
    rows = [['rest choice TV', '0'] + [fmt(tv_distance(h['rest'], arms[n]['rest']), 3) for n in names],
            ['  ↳ rest choice', dist_row(h['rest'], arms[names[0]]['rest'], 4)] + [''] * len(names),
            ['heal amount / max HP (mean)', fmt(statistics.mean(h['heal_ratio']) if h['heal_ratio'] else None, 3)] + [fmt(statistics.mean(arms[n]['heal_ratio']) if arms[n]['heal_ratio'] else None, 3) for n in names],
            ['shop gold spent mean / p50', (lambda a: f"{a['mean']:.0f} / {a['p50']:.0f}" if a else '—')(num_stats(h['shop_spent']))] + [(lambda a: f"{a['mean']:.0f} / {a['p50']:.0f}" if a else '—')(num_stats(arms[n]['shop_spent'])) for n in names],
            ['shop stock size TV', '0'] + [fmt(tv_distance(h['shop_cards'], arms[n]['shop_cards']), 3) for n in names]]
    for what in ('card', 'relic', 'purge'):
        rows.append([f'shop visits buying a {what} %', fmt(pct(h['shop_bought'], (what, True)), 1)] + [fmt(pct(arms[n]['shop_bought'], (what, True)), 1) for n in names])
    table(['metric', 'human', *names], rows)
    lines.append('')
    lines.append('Event frequency TV per act and the events whose mean ΔHP deviates most (human → first arm):')
    lines.append('')
    rows = []
    for act in ('OVERGROWTH', 'UNDERDOCKS', 'HIVE', 'GLORY'):
        rows.append([act, 'frequency TV'] + [fmt(tv_distance(h['event_freq'][act], arms[n]['event_freq'][act]), 3) for n in names] + [dist_row(h['event_freq'][act], arms[names[0]]['event_freq'][act], 4)])
    table(['act', 'metric', *[f'TV {n}' for n in names], 'top events'], rows)
    lines.append('')
    devs = []
    for event, hv in h['event_dhp'].items():
        av = arms[names[0]]['event_dhp'].get(event)
        if len(hv) >= 30 and av and len(av) >= 30:
            devs.append((abs(statistics.mean(av) - statistics.mean(hv)), event, statistics.mean(hv), statistics.mean(av),
                         statistics.mean(h['event_dgold'][event]), statistics.mean(arms[names[0]]['event_dgold'][event]), len(hv), len(av)))
    devs.sort(reverse=True)
    table(['event', 'ΔHP human', f'ΔHP {names[0]}', 'Δgold human', f'Δgold {names[0]}', 'n human', f'n {names[0]}'],
          [[e, f'{a:+.1f}', f'{b:+.1f}', f'{c:+.1f}', f'{d:+.1f}', nh, na] for _, e, a, b, c, d, nh, na in devs[:12]])

    # 7. combat
    header('7. Combat outcomes per encounter')
    lines.append('Mean HP lost per fight: human (holdout, includes potions and player skill) vs each arm; `F mean` is the model oracle\'s expected loss before noise/death sampling; `teacher` is the mean CombatSolver label on real human builds from the training snapshot. Death % = fights that ended the run.')
    lines.append('')
    model_arm = next((n for n in names if '/F/' in n and arms[n]['combat_expected']), None)
    rows = []
    abs_err = defaultdict(list)
    for act in ('OVERGROWTH', 'UNDERDOCKS', 'HIVE', 'GLORY'):
        encs = sorted(h['encounters'][act]['monster'].items() | h['encounters'][act]['elite'].items() | h['encounters'][act]['boss'].items(), key=lambda kv: -kv[1])
        for enc, count in encs:
            hv = h['damage'].get(enc, [])
            if len(hv) < 20:
                continue
            hm = statistics.mean(hv)
            row = [act, enc, len(hv), f'{hm:.1f}', f"{100 * statistics.mean(h['death_rate'][enc]):.1f}"]
            for n in names:
                av = arms[n]['damage'].get(enc, [])
                if av:
                    row.append(f'{statistics.mean(av):.1f} ({statistics.mean(av) - hm:+.1f}) / {100 * statistics.mean(arms[n]["death_rate"][enc]):.1f}%')
                    abs_err[n].append(abs(statistics.mean(av) - hm))
                else:
                    row.append('—')
            fm = statistics.mean(arms[model_arm]['combat_expected'][enc]) if model_arm and arms[model_arm]['combat_expected'].get(enc) else None
            row.append(fmt(fm, 1))
            tm = teacher_means.get(f'{act}:{enc}') if teacher_means else None
            row.append(fmt(tm, 1))
            rows.append(row)
    table(['act', 'encounter', 'n human', 'human HP lost', 'human death %', *[f'{n} (Δ) / death' for n in names], 'F mean', 'teacher'], rows)
    lines.append('')
    lines.append('Mean absolute deviation of per-encounter mean HP lost: ' + ', '.join(f'`{n}` {statistics.mean(v):.2f} HP' for n, v in abs_err.items() if v) + '.')
    payload['sections']['combat_mae'] = {n: statistics.mean(v) for n, v in abs_err.items() if v}
    lines.append('')
    rows = []
    for act in ('OVERGROWTH', 'UNDERDOCKS', 'HIVE', 'GLORY'):
        hv = h['hp_before_combat'][act]
        if hv:
            rows.append([act, f'{statistics.mean(hv):.3f}'] + [fmt(statistics.mean(arms[n]['hp_before_combat'][act]) if arms[n]['hp_before_combat'][act] else None, 3) for n in names])
    lines.append('HP ratio when entering combat (mean):')
    lines.append('')
    table(['act', 'human', *names], rows)

    # 8. F on human builds
    if human_builds:
        header('8. Combat oracle on the actual human builds (holdout)')
        lines.append(f"{human_builds['fights']} recorded human fights from {human_builds['runs']} held-out runs were re-scored with F on the "
                     'exact pre-combat deck/relics the player had. This isolates oracle bias from deck quality: `human` is the recorded HP '
                     'lost, `F` the predicted expected loss. Fights where the player used no potion are the fairest comparison with F/teacher, which never see potions.')
        lines.append('')
        rows = []
        for key in ('all', 'no_potion', 'potion'):
            b = human_builds['bias'].get(key)
            if b:
                rows.append([key, b['n'], f"{b['human_mean']:.2f}", f"{b['f_mean']:.2f}", f"{b['bias']:+.2f}", f"{b['mae']:.2f}",
                             f"{100 * b['human_death']:.1f}", f"{100 * b['f_death']:.1f}", f"{100 * b['f_sampled_death']:.1f}"])
        table(['fights', 'n', 'human HP lost', 'F mean', 'bias (F − human)', 'MAE per fight', 'human death %', 'F death head %', 'F sampled death %'], rows)
        lines.append('')
        lines.append('Per room type / act (no-potion fights):')
        lines.append('')
        rows = []
        for key, b in sorted(human_builds['by_group'].items()):
            rows.append([key, b['n'], f"{b['human_mean']:.2f}", f"{b['f_mean']:.2f}", f"{b['bias']:+.2f}", f"{b['mae']:.2f}",
                         f"{100 * b['human_death']:.1f}", f"{100 * b['f_death']:.1f}"])
        table(['group', 'n', 'human HP lost', 'F mean', 'bias', 'MAE', 'human death %', 'F death head %'], rows)
        lines.append('')
        lines.append('Encounters with the largest |bias| (no-potion fights, n ≥ 20):')
        lines.append('')
        rows = []
        for key, b in sorted(human_builds['by_encounter'].items(), key=lambda kv: -abs(kv[1]['bias']))[:20]:
            rows.append([key, b['n'], f"{b['human_mean']:.1f}", f"{b['f_mean']:.1f}", f"{b['bias']:+.1f}", f"{100 * b['human_death']:.1f}", f"{100 * b['f_death']:.1f}"])
        table(['act:encounter', 'n', 'human HP lost', 'F mean', 'bias', 'human death %', 'F death head %'], rows)
        payload['sections']['f_on_human_builds'] = {k: v for k, v in human_builds.items() if k != 'by_encounter'}

    header('9. Known gaps in v0 (not modelled)')
    for gap in meta.get('gaps', []):
        lines.append(f'- {gap}')
    return '\n'.join(lines) + '\n', payload


def score_human_builds(holdout: dict, catalog, oracle: ModelOracle, max_runs: int, log=print):
    """Re-score recorded human fights with F on the reconstructed pre-combat build."""
    from damage_model.run_import import RunRejected, build_for, reconstruct
    from .oracle import CombatRequest
    fights, used_runs, rejected = [], 0, Counter()
    for key, run in list(holdout.items())[:max_runs]:
        try:
            floors = reconstruct(run, catalog)
        except (RunRejected, ValueError) as exc:
            rejected[str(exc)[:40]] += 1
            continue
        used_runs += 1
        records = floor_records(run, key)
        for snap, rec in zip(floors, records):
            if not snap['simple_combat'] or snap['target'] is None or rec['encounter'] != snap['target']:
                continue
            if rec.get('abandoned') and rec['final']:
                continue
            if not oracle.covers(rec['act_id'], rec['encounter']):
                continue
            try:
                build, _ = build_for(snap, key, catalog)
            except (RunRejected, ValueError) as exc:   # catalog.validate raises ValueError for disallowed cards/relics
                rejected[str(exc)[:40]] += 1
                continue
            fights.append((CombatRequest(build, rec['encounter'], rec['hp_before'], rec['max_hp_after'], rec['room_types'][0]), rec))
    if not fights:
        return None
    mean, _std, death, _untrained = oracle.predict([f[0] for f in fights])
    sampled = oracle.resolve([f[0] for f in fights])

    def agg(indices):
        if not indices:
            return None
        hv = np.array([fights[i][1]['damage_taken'] for i in indices], dtype=float)
        fv = mean[indices]
        return {'n': int(len(indices)), 'human_mean': float(hv.mean()), 'f_mean': float(fv.mean()), 'bias': float((fv - hv).mean()),
                'mae': float(np.abs(fv - hv).mean()), 'human_death': float(np.mean([fights[i][1]['hp_after'] <= 0 for i in indices])),
                'f_death': float(death[indices].mean()), 'f_sampled_death': float(np.mean([sampled[i].died for i in indices]))}

    no_potion = [i for i, f in enumerate(fights) if f[1]['potions_used'] == 0]
    potion = [i for i, f in enumerate(fights) if f[1]['potions_used'] > 0]
    groups = defaultdict(list)
    per_enc = defaultdict(list)
    for i in no_potion:
        rec = fights[i][1]
        groups[f"{rec['act_id']}:{rec['room_types'][0]}"].append(i)
        per_enc[f"{rec['act_id']}:{rec['encounter']}"].append(i)
    result = {'runs': used_runs, 'fights': len(fights), 'rejected': dict(rejected.most_common(5)),
              'bias': {'all': agg(list(range(len(fights)))), 'no_potion': agg(no_potion), 'potion': agg(potion)},
              'by_group': {k: agg(v) for k, v in groups.items()},
              'by_encounter': {k: agg(v) for k, v in per_enc.items() if len(v) >= 20}}
    log(json.dumps({'event': 'human_builds_scored', 'runs': used_runs, 'fights': len(fights), 'rejected': sum(rejected.values()),
                    'bias_no_potion': round(result['bias']['no_potion']['bias'], 2) if result['bias']['no_potion'] else None}))
    return result


GAPS = [
    'Potions are ignored entirely (no potion drops, no use); the teacher and F are trained without potions as well, so the human column is the only one that benefits from potions.',
    'Map layout is generated STS1-style; only the visited-path type mix is checked against humans (unvisited nodes are unobservable).',
    'Events replay recorded human outcomes irrespective of the current state (no option choice, HP-dependent choices not conditioned, outcomes clamped so events never kill).',
    'Relic pickup effects only for relics whose effect shows up as HP/max HP/gold/cards deltas on ancient/treasure/combat floors; shop-only relics, card enchantments and rest-site options unlocked by relics (DIG, LIFT, COOK, …) are absent.',
    'Rest site heal is fixed to 30 % of max HP; SMITH upgrades only; no dual choices.',
    'Card rewards always offer 3 cards from the Silent pool with fitted rarity odds; no colorless/attack-only rewards, no reward-modifying relics.',
    'Combat: F returns an expected loss; realised loss = round(mean + pessimism·std + N(0, noise_sd)), plus a death draw from the death head. Human damage includes potions, misplays and lower-than-70 starting HP.',
    'Baseline policies are hand-written and do not use F; human decision quality is not reproduced (see the HP-when-entering-combat row).',
]


# ---------------------------------------------------------------------- driver
def teacher_target_means(snapshot_dir: Path):
    """Mean CombatSolver label (HP lost at 70 max HP) per act:target from a training snapshot."""
    battles = snapshot_dir / 'battles.parquet'
    if not battles.exists():
        return None
    import pyarrow.parquet as pq
    table = pq.read_table(battles).to_pandas()
    cols = set(table.columns)
    if not {'target_id', 'act_id'} <= cols:
        return None
    loss_col = next((c for c in ('hp_loss', 'expected_hp_loss', 'mean_hp_loss') if c in cols), None)
    if loss_col is None:
        return None
    if 'kind' in cols:   # real human builds only, not mutated ones
        table = table[table['kind'] == 'real']
    grouped = table.groupby(['act_id', 'target_id'])[loss_col].mean()
    return {f'{a}:{t}': float(v) for (a, t), v in grouped.items()}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--tables', default=str(DEFAULT_TABLES))
    parser.add_argument('--episodes', type=int, default=2000)
    parser.add_argument('--checkpoint', action='append', default=[], help='F checkpoint dir (repeatable, forms an ensemble)')
    parser.add_argument('--device', default='cpu')
    parser.add_argument('--pessimism', type=float, default=0.0)
    parser.add_argument('--noise-sd', type=float, default=0.0)
    parser.add_argument('--no-death-head', action='store_true')
    parser.add_argument('--snapshot', default=None, help='training snapshot dir for teacher label means')
    parser.add_argument('--human-build-runs', type=int, default=400, help='holdout runs whose fights are re-scored with F (0 to skip)')
    parser.add_argument('--greedy-episodes', type=int, default=500, help='episodes for the F-lookahead policy arm (0 to skip)')
    parser.add_argument('--output', default=None, help='report dir (default reports/sim/<stamp>)')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--catalog', default=str(ROOT / 'catalogs/game-0.111.0.raw.json'))
    parser.add_argument('--config', default=str(ROOT / 'configs/real-runs-8s.json'))
    args = parser.parse_args()

    from damage_model.catalog import Catalog
    catalog = Catalog.load(args.catalog, args.config)
    tables = load_tables(args.tables)
    stamp = time.strftime('%Y%m%d-%H%M%S')
    out = Path(args.output) if args.output else ROOT / 'reports/sim' / stamp
    out.mkdir(parents=True, exist_ok=True)

    runs = load_runs()
    _fit, holdout = split_runs(runs, tables.get('holdout_fraction', 0.2))
    human = summarize(all_floor_records(holdout), catalog)
    print(json.dumps({'event': 'human_summarized', 'holdout_runs': human['runs']}))

    arms, arm_meta = {}, {}
    empirical = EmpiricalOracle(tables['human_damage'], seed=args.seed)
    for policy in (HeuristicPolicy(seed=args.seed), RandomPolicy(seed=args.seed)):
        name = f'sim/empirical/{policy.name}'
        records, _ = rollout(tables, catalog, empirical, policy, args.episodes, seed=args.seed)
        arms[name] = summarize(records, catalog)
        arm_meta[name] = f'human damage histograms, {policy.name} policy'
    human_builds = None
    if args.checkpoint:
        oracle = ModelOracle(args.checkpoint, device=args.device, pessimism=args.pessimism, noise_sd=args.noise_sd,
                             use_death_head=not args.no_death_head, seed=args.seed)
        name = 'sim/F/heuristic'
        records, _ = rollout(tables, catalog, oracle, HeuristicPolicy(seed=args.seed), args.episodes, seed=args.seed)
        arms[name] = summarize(records, catalog)
        arm_meta[name] = (f"F ensemble of {len(args.checkpoint)} ({', '.join(Path(c).name for c in args.checkpoint)}), "
                          f"pessimism={args.pessimism}, noise_sd={args.noise_sd}, death_head={not args.no_death_head}, heuristic policy")
        if args.greedy_episodes > 0:
            name = 'sim/F/greedy_f'
            records, _ = rollout(tables, catalog, oracle, GreedyFPolicy(oracle, seed=args.seed), args.greedy_episodes, seed=args.seed, batch=64)
            arms[name] = summarize(records, catalog)
            arm_meta[name] = 'same F oracle; card/smith/ancient choices by one-step F lookahead, map/shop heuristic'
        if args.human_build_runs > 0:
            human_builds = score_human_builds(holdout, catalog, oracle, args.human_build_runs)
    teacher = teacher_target_means(Path(args.snapshot)) if args.snapshot else None
    meta = {'stamp': stamp, 'tables': tables['version'], 'fit_runs': tables['fit_runs'], 'holdout_runs': human['runs'],
            'episodes': args.episodes, 'arms': arm_meta, 'gaps': GAPS, 'args': vars(args)}
    markdown, payload = build_report(human, arms, meta, teacher, human_builds)
    (out / 'deviation.md').write_text(markdown, encoding='utf-8')
    (out / 'summary.json').write_text(json.dumps(payload, indent=1, default=str), encoding='utf-8')
    print(json.dumps({'event': 'report_written', 'path': str(out / 'deviation.md')}))


if __name__ == '__main__':
    main()
