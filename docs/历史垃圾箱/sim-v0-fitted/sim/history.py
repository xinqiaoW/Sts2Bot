"""Load Spire Codex ``.run`` histories and flatten them into per-floor records.

Runs are read from the ``source_runs`` tables of the collection databases (read
only). The same 8,062 runs are present in v2/v3/v4; they are deduplicated by
``run_hash``. Only solo Silent, A10, standard mode, game 0.111.0, schema 10 runs
with the vanilla act sequence are kept.

The flattened floor record format is shared with ``sim.rollout`` so that human
and simulated trajectories can be compared with the same code.
"""
from __future__ import annotations

import hashlib
import json
import pickle
import sqlite3
from pathlib import Path

from . import ROOT

DEFAULT_DBS = ('data/collection-real-runs-v4.sqlite',)
DEFAULT_CACHE = ROOT / 'data/sim/runs-cache.pkl'
VANILLA_ACT1 = ('OVERGROWTH', 'UNDERDOCKS')
VANILLA_ACTS = ('HIVE', 'GLORY')
START_HP, START_MAX_HP, START_GOLD = 56, 70, 99   # A10 Silent after the ascension HP penalty


def entity(value):
    """``'CARD.STRIKE'`` -> ``'STRIKE'``; passthrough for bare ids."""
    if value is None:
        return None
    value = str(value)
    return value.split('.', 1)[1] if '.' in value else value


def is_vanilla_silent_a10(run) -> bool:
    if run.get('schema_version') != 10 or run.get('build_id') != 'v0.111.0':
        return False
    if run.get('ascension') != 10 or run.get('game_mode') != 'standard' or run.get('modifiers'):
        return False
    players = run.get('players', [])
    if len(players) != 1 or players[0].get('character') != 'CHARACTER.SILENT':
        return False
    acts = [entity(a) for a in run.get('acts', [])]
    if len(acts) < 3 or acts[0] not in VANILLA_ACT1 or tuple(acts[1:3]) != VANILLA_ACTS:
        return False
    if not run.get('map_point_history'):
        return False
    return True


def load_runs(dbs=DEFAULT_DBS, cache: Path | None = DEFAULT_CACHE, log=print) -> dict:
    """Return ``{run_hash: run_json}`` for all accepted runs (cached as a pickle)."""
    if cache and Path(cache).exists():
        with Path(cache).open('rb') as stream:
            cached = pickle.load(stream)
        return {k: r for k, r in cached.items() if is_vanilla_silent_a10(r)}
    runs = {}
    for db in dbs:
        path = ROOT / db
        if not path.exists():
            continue
        con = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
        try:
            for run_hash, body in con.execute('select hash, body from source_runs'):
                run = json.loads(body)
                key = run.get('run_hash') or run_hash
                if key in runs or not is_vanilla_silent_a10(run):
                    continue
                runs[key] = run
        finally:
            con.close()
        log(json.dumps({'event': 'runs_loaded', 'db': db, 'total': len(runs)}))
    if cache:
        Path(cache).parent.mkdir(parents=True, exist_ok=True)
        with Path(cache).open('wb') as stream:
            pickle.dump(runs, stream, protocol=pickle.HIGHEST_PROTOCOL)
    return runs


def split_runs(runs: dict, holdout_fraction=0.2, salt='sim-calibration-v0'):
    """Deterministic fit/holdout split by run hash. Tables are fitted on ``fit``; the
    deviation report compares against ``holdout`` only."""
    fit, holdout = {}, {}
    threshold = int(holdout_fraction * 100)
    for key, run in runs.items():
        bucket = int(hashlib.sha256(f'{salt}:{key}'.encode()).hexdigest()[:8], 16) % 100
        (holdout if bucket < threshold else fit)[key] = run
    return fit, holdout


def floor_records(run, run_hash=None):
    """Flatten one run into floor records (one dict per visited map point).

    Fields (``None`` when not applicable):
      run, act_index (0-based), act_id, floor (0-based within act, 0 = ancient),
      node_type, room_types, encounter, event, hp_before, hp_after, max_hp_after,
      gold_after, gold_gained, gold_spent, damage_taken, hp_healed, max_hp_gained,
      max_hp_lost, card_options, card_option_ids, card_picked, rest_choices,
      upgraded, cards_gained, cards_removed, relics_gained, relic_options,
      ancient_options, ancient_choice, deck_size_after, relic_count_after,
      potions_used, final (True on the run's last record), win.
    """
    player = run['players'][0]
    pid = player['id']
    acts = [entity(a) for a in run['acts']]
    history = run['map_point_history']
    total = sum(len(nodes) for nodes in history)
    hp, max_hp, gold = START_HP, START_MAX_HP, START_GOLD
    deck_size = 13   # 12 starting cards + Ascender's Bane
    relic_count = 1
    seen = 0
    records = []
    for act_index, nodes in enumerate(history[:3]):
        act_id = acts[act_index]
        for floor, node in enumerate(nodes):
            seen += 1
            stats = [s for s in node.get('player_stats', []) if s.get('player_id') == pid]
            stats = stats[0] if stats else {}
            rooms = node.get('rooms', [])
            room_types = [r.get('room_type') for r in rooms]
            encounters = [entity(r['model_id']) for r in rooms if str(r.get('model_id', '')).startswith('ENCOUNTER.')]
            events = [entity(r['model_id']) for r in rooms if str(r.get('model_id', '')).startswith('EVENT.')]
            gained = [entity(c['id']) for c in stats.get('cards_gained', [])]
            removed = [entity(c['id']) for c in stats.get('cards_removed', [])]
            relics_gained = [entity(x['choice']) for x in stats.get('relic_choices', []) if x.get('was_picked')]
            relics_gained += [entity(x) for x in stats.get('bought_relics', [])]
            relics_gained = list(dict.fromkeys(relics_gained))
            deck_size += len(gained) - len(removed)
            relic_count += len(relics_gained) - len(stats.get('relics_removed', []))
            choices = stats.get('card_choices') or []
            ancient = stats.get('ancient_choice') or []
            record = {
                'run': run_hash, 'act_index': act_index, 'act_id': act_id, 'floor': floor,
                'node_type': node.get('map_point_type'), 'room_types': room_types,
                'encounter': encounters[0] if len(encounters) == 1 and len(rooms) == 1 else None,
                'event': events[0] if events else None,
                'hp_before': hp, 'hp_after': stats.get('current_hp', hp), 'max_hp_after': stats.get('max_hp', max_hp),
                'gold_before': gold, 'gold_after': stats.get('current_gold', gold),
                'gold_gained': stats.get('gold_gained', 0), 'gold_spent': stats.get('gold_spent', 0),
                'gold_lost': stats.get('gold_lost', 0) + stats.get('gold_stolen', 0),
                'damage_taken': stats.get('damage_taken', 0), 'hp_healed': stats.get('hp_healed', 0),
                'max_hp_gained': stats.get('max_hp_gained', 0), 'max_hp_lost': stats.get('max_hp_lost', 0),
                'card_options': len(choices) if choices else None,
                'card_option_ids': [entity(x['card']['id']) for x in choices] if choices else None,
                'card_picked': any(x.get('was_picked') for x in choices) if choices else None,
                'rest_choices': list(stats.get('rest_site_choices', [])) or None,
                'upgraded': [entity(c) for c in stats.get('upgraded_cards', [])],
                'cards_gained': gained, 'cards_removed': removed,
                'cards_transformed': len(stats.get('cards_transformed', [])),
                'cards_enchanted': len(stats.get('cards_enchanted', [])),
                'relics_gained': relics_gained,
                'relic_options': [entity(x['choice']) for x in stats.get('relic_choices', [])] or None,
                'ancient_options': [x.get('TextKey') for x in ancient] or None,
                'ancient_choice': next((x.get('TextKey') for x in ancient if x.get('was_chosen')), None),
                'deck_size_after': deck_size, 'relic_count_after': relic_count,
                'potions_used': len(stats.get('potion_used', [])),
                'final': seen == total, 'win': bool(run.get('win')),
                # 27 % of runs were quit early (often right at the ancient); their floors
                # are valid observations but their ending is not a game outcome.
                'abandoned': bool(run.get('was_abandoned')),
            }
            hp, max_hp, gold = record['hp_after'], record['max_hp_after'], record['gold_after']
            records.append(record)
    return records


def all_floor_records(runs: dict):
    out = []
    for key, run in runs.items():
        out.extend(floor_records(run, key))
    return out
