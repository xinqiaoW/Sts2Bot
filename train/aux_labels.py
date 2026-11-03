"""Extract and load per-battle auxiliary process supervision labels from combat traces.

The 9 auxiliary supervision signals per battle row are:
0. ``turns_norm``               : log1p(finished_turn) (available for 100% of rows)
1. ``dmg_per_turn``             : total damage (HP + enemy block stripped) / turns
2. ``dmg_stability``            : mean(turn_dmg) / (mean(turn_dmg) + std(turn_dmg) + 1e-5)
3. ``blk_per_turn``             : total block gained / turns
4. ``blk_stability``            : non-lethal turn block stability mean / (mean + std + 1e-5)
5. ``eff_energy_gen_per_turn``  : (energy generated + Sly free card cost) / turns
6. ``eff_energy_used_per_turn`` : (energy spent + Sly free card cost) / turns
7. ``extra_draw_per_turn``      : extra cards drawn beyond standard 5 per turn / turns
8. ``cards_per_turn``           : (cards played + Sly auto-played cards) / turns
"""
from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
import json
import math
import os
from pathlib import Path
import sqlite3
import time

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

AUX_COLUMNS = (
    'dmg_per_turn',
    'dmg_stability',
    'blk_per_turn',
    'blk_stability',
    'eff_energy_gen_per_turn',
    'eff_energy_used_per_turn',
    'extra_draw_per_turn',
    'cards_per_turn',
)
NUM_AUX_TARGETS = 1 + len(AUX_COLUMNS)  # turns_norm + 8 trace metrics = 9

SHIV_GEN_CARDS = frozenset({'BLADE_DANCE', 'CLOAK_AND_DAGGER', 'HIDDEN_DAGGERS', 'UP_MY_SLEEVE', 'FAN_OF_KNIVES'})
BLOCK_CARDS = frozenset({
    'DEFEND_SILENT', 'SURVIVOR', 'DASH', 'LEG_SWEEP', 'CLOAK_AND_DAGGER',
    'BACKFLIP', 'DODGE_AND_ROLL', 'BLUR', 'DEFLECT', 'ESCAPE_PLAN',
    'SIDESTEP', 'UNTOUCHABLE', 'MIRAGE', 'SHIMMER',
})


def _extract_cost(csk: str) -> tuple[bool, int]:
    pos = csk.find('|energy=')
    if pos < 0:
        return False, 0
    sub = csk[pos + 8:]
    bar = sub.find('|')
    if bar >= 0:
        sub = sub[:bar]
    is_x = sub.startswith('True:')
    colon = sub.find(':')
    val = int(sub[colon + 1:]) if colon >= 0 else 0
    return is_x, max(0, val)


def _extract_int_var(csk: str, var_prefix: str) -> int:
    pos = csk.find(var_prefix)
    if pos < 0:
        return 0
    start = pos + len(var_prefix)
    end = start
    n = len(csk)
    while end < n and csk[end].isdigit():
        end += 1
    return int(csk[start:end]) if end > start else 0


def parse_trace_metrics(raw_json: str) -> tuple[float, float, float, float, float, float, float, float] | None:
    """Parse 8 per-turn trace metrics from a job's ``result`` JSON string."""
    try:
        res = json.loads(raw_json)
    except Exception:
        return None
    obs = res.get('trainingObservation')
    ex = res.get('execution')
    if not obs or not ex:
        return None
    trace = ex.get('trace')
    if not trace:
        return None
    turns = res.get('finishedTurn') or len(trace)
    if turns <= 0:
        turns = 1
    player_died = bool(obs.get('playerDied'))
    init_build = obs.get('initialBuild') or {}
    relic_ids = {r['id'] for r in init_build.get('relics', ())}
    has_ice_cream = 'ICE_CREAM' in relic_ids
    has_orichalcum = 'ORICHALCUM' in relic_ids
    has_cloak_clasp = 'CLOAK_CLASP' in relic_ids
    has_ninja_scroll = 'NINJA_SCROLL' in relic_ids

    total_cards_played = 0
    total_sly_played = 0
    total_energy_spent = 0
    total_sly_energy = 0
    total_energy_gen = 0
    total_extra_drawn = 0

    enemy_max_hp: dict[int, int] = {}
    enemy_last_hp: dict[int, int] = {}
    prev_enemies: dict[int, tuple[int, int, int]] = {}

    retained_from_prev_turn = 0
    prev_inf_blades = 0
    prev_tools_power = 0
    prev_end_energy = 0

    turn_dmgs: list[float] = []
    turn_blks: list[float] = []

    for ti, t_obj in enumerate(trace):
        t = t_obj.get('turn', ti + 1)
        steps = t_obj['deployment']['trace']
        if not steps:
            turn_gen = 3
            total_energy_gen += turn_gen
            prev_end_energy = (prev_end_energy + turn_gen) if has_ice_cream else 0
            total_extra_drawn += prev_tools_power
            retained_from_prev_turn = 0
            turn_dmgs.append(0.0)
            turn_blks.append(0.0)
            continue

        prev_block = 0
        prev_H_len = 0
        turn_drawn = 0
        turn_spent = 0
        t_blk = 0
        t_dmg = 0
        prev_e = None

        for si, s in enumerate(steps):
            act = s['action']
            live_str = s.get('live', '')
            cid = act.get('CardId', '')
            csk = act.get('CardStateKey', '')

            blk_pos = live_str.find(';block=')
            cur_block = int(live_str[blk_pos + 7 : live_str.find(';', blk_pos + 7)]) if blk_pos >= 0 else 0
            eng_pos = live_str.find(';energy=')
            curr_e = int(live_str[eng_pos + 8 : live_str.find(';', eng_pos + 8)]) if eng_pos >= 0 else 0

            is_x, cost = _extract_cost(csk)
            if is_x:
                cost = max(0, (prev_e if prev_e is not None else 3) - curr_e)
            if cid:
                total_cards_played += 1
                turn_spent += cost

            choice = act.get('Choice')
            disc_cnt = 0
            if choice and choice.get('Cards') and choice.get('SourcePile') == 2:
                cards_c = choice['Cards']
                disc_cnt = len(cards_c)
                for cc in cards_c:
                    sk = cc.get('StateKey', '')
                    if '|sly=True|' in sk and cc.get('CardId') not in ('REFLEX', 'TACTICIAN'):
                        total_sly_played += 1
                        _, scost = _extract_cost(sk)
                        total_sly_energy += scost

            combat_over = ';H=;D=;C=;X=;' in live_str
            if not combat_over:
                if cur_block > prev_block:
                    t_blk += (cur_block - prev_block)
                prev_block = cur_block

                h_pos = live_str.find(';H=')
                h_end = live_str.find(';D=', h_pos) if h_pos >= 0 else -1
                h_str = live_str[h_pos + 3 : h_end] if (h_pos >= 0 and h_end >= 0) else ''
                curr_H_len = h_str.count('/baselib=')
                played_cnt = 1 if cid else 0
                gen_shivs = 0
                if cid in SHIV_GEN_CARDS:
                    gen_shivs = _extract_int_var(csk, 'Shivs=') or _extract_int_var(csk, 'Cards=')

                if si == 0:
                    start_gen = prev_inf_blades + (3 if (t == 1 and has_ninja_scroll) else 0)
                    drawn_now = max(0, curr_H_len + played_cnt + disc_cnt + prev_tools_power - retained_from_prev_turn - start_gen - gen_shivs)
                else:
                    drawn_now = max(0, curr_H_len - (prev_H_len - played_cnt - disc_cnt + gen_shivs))
                turn_drawn += drawn_now
                prev_H_len = curr_H_len

                e_pos = live_str.find(';E0=')
                if e_pos >= 0:
                    ai_pos = live_str.find(';AI0=', e_pos)
                    if ai_pos < 0:
                        ai_pos = h_pos
                    e_chunk = live_str[e_pos + 1 : ai_pos]
                    cur_enemies: dict[int, tuple[int, int, int]] = {}
                    for e_item in e_chunk.split(';'):
                        if e_item.startswith('E') and '=' in e_item:
                            f = e_item.split('=', 1)[1].split('/')
                            if len(f) >= 6:
                                ecid, ehp, emhp, eblk = int(f[0]), int(f[3]), int(f[4]), int(f[5])
                                cur_enemies[ecid] = (ehp, emhp, eblk)
                                if ecid not in enemy_max_hp:
                                    enemy_max_hp[ecid] = emhp
                                    enemy_last_hp[ecid] = emhp
                                if ecid in prev_enemies:
                                    p_ehp, _, p_eblk = prev_enemies[ecid]
                                    if si == 0 and ti > 0:
                                        if ehp < p_ehp and turn_dmgs:
                                            # Enemy-turn poison/thorns damage belongs to prev turn or this turn step 0
                                            t_dmg += (p_ehp - ehp)
                                    else:
                                        if ehp < p_ehp:
                                            t_dmg += (p_ehp - ehp)
                                        if eblk < p_eblk:
                                            t_dmg += (p_eblk - eblk)
                                else:
                                    if ehp < emhp:
                                        t_dmg += (emhp - ehp)
                                enemy_last_hp[ecid] = ehp
                    for pecid, (p_ehp, _, p_eblk) in prev_enemies.items():
                        if pecid not in cur_enemies and enemy_last_hp.get(pecid, 0) > 0:
                            t_dmg += enemy_last_hp[pecid] + (p_eblk if si > 0 else 0)
                            enemy_last_hp[pecid] = 0
                    prev_enemies = cur_enemies
            else:
                if cid in BLOCK_CARDS:
                    t_blk += _extract_int_var(csk, 'Block=')
                if si == 0:
                    turn_drawn += 5 + prev_tools_power

            prev_e = curr_e

        last_live = steps[-1].get('live', '')
        combat_over = ';H=;D=;C=;X=;' in last_live
        eng_pos = last_live.find(';energy=')
        end_e = int(last_live[eng_pos + 8 : last_live.find(';', eng_pos + 8)]) if eng_pos >= 0 else 0
        carry = prev_end_energy if has_ice_cream else 0
        turn_gen = max(0, turn_spent + end_e - carry)
        total_energy_gen += turn_gen
        total_energy_spent += turn_spent
        prev_end_energy = end_e

        if not combat_over:
            if has_orichalcum and prev_block == 0:
                t_blk += 6
            h_pos = last_live.find(';H=')
            h_end = last_live.find(';D=', h_pos) if h_pos >= 0 else -1
            h_str = last_live[h_pos + 3 : h_end] if (h_pos >= 0 and h_end >= 0) else ''
            end_h_len = h_str.count('/baselib=')
            if has_cloak_clasp:
                t_blk += end_h_len

            p_pos = last_live.find(';P=')
            p_end = last_live.find(';R=', p_pos) if p_pos >= 0 else -1
            p_str = last_live[p_pos + 3 : p_end] if (p_pos >= 0 and p_end >= 0) else ''

            ret_cnt = 0
            for rc in h_str.split('/baselib=-,'):
                if rc:
                    parts = rc.split('/')
                    if len(parts) >= 7 and parts[6] == 'True':
                        ret_cnt += 1
            if 'WELL_LAID_PLANS' in p_str:
                ret_cnt = min(end_h_len, ret_cnt + 1)
            retained_from_prev_turn = ret_cnt

            prev_inf_blades = _extract_int_var(p_str, 'INFINITE_BLADES_POWER=')
            prev_tools_power = _extract_int_var(p_str, 'TOOLS_OF_THE_TRADE_POWER=')
        else:
            retained_from_prev_turn = 0
            prev_inf_blades = 0
            prev_tools_power = 0

        total_extra_drawn += max(0, turn_drawn - 5)
        turn_dmgs.append(float(t_dmg))
        turn_blks.append(float(t_blk))

    if not player_died and turn_dmgs:
        rem = sum(max(0, ehp) for ehp in enemy_last_hp.values())
        turn_dmgs[-1] += float(rem)

    inv_t = 1.0 / turns
    dmg_mean = sum(turn_dmgs) * inv_t
    if len(turn_dmgs) > 1:
        dmg_var = sum((x - dmg_mean) ** 2 for x in turn_dmgs) / len(turn_dmgs)
        dmg_std = math.sqrt(dmg_var)
    else:
        dmg_std = 0.0
    dmg_stability = dmg_mean / (dmg_mean + dmg_std + 1e-5)

    blk_mean = sum(turn_blks) * inv_t
    # For block stability, exclude the final lethal turn when the player wins so fast kills aren't penalized
    surv_blks = turn_blks[:-1] if (not player_died and len(turn_blks) > 1) else turn_blks
    s_mean = sum(surv_blks) / len(surv_blks) if surv_blks else 0.0
    if len(surv_blks) > 1:
        s_var = sum((x - s_mean) ** 2 for x in surv_blks) / len(surv_blks)
        s_std = math.sqrt(s_var)
    else:
        s_std = 0.0
    blk_stability = s_mean / (s_mean + s_std + 1e-5)

    return (
        float(dmg_mean),
        float(dmg_stability),
        float(blk_mean),
        float(blk_stability),
        float((total_energy_gen + total_sly_energy) * inv_t),
        float((total_energy_spent + total_sly_energy) * inv_t),
        float(total_extra_drawn * inv_t),
        float((total_cards_played + total_sly_played) * inv_t),
    )


def _worker_scan_range(args):
    db_path, low, high, recover = args
    out_ids = []
    out_vals = []
    con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
    con.execute('PRAGMA query_only=ON')
    con.execute('PRAGMA cache_size=-16384')
    step = 512

    def fetch_range(lo, hi):
        try:
            return con.execute(
                'SELECT id, status, result FROM jobs NOT INDEXED WHERE rowid BETWEEN ? AND ? ORDER BY rowid',
                (lo, hi),
            ).fetchall()
        except (sqlite3.DatabaseError, UnicodeError):
            if not recover or lo == hi:
                return []
            mid = (lo + hi) // 2
            return fetch_range(lo, mid) + fetch_range(mid + 1, hi)

    for start in range(low, high + 1, step):
        end = min(high, start + step - 1)
        rows = fetch_range(start, end)
        for jid, status, res_str in rows:
            if status != 'complete' or not res_str:
                continue
            vals = parse_trace_metrics(res_str)
            if vals is not None:
                out_ids.append(jid)
                out_vals.append(vals)
    con.close()
    return out_ids, np.asarray(out_vals, dtype=np.float32) if out_vals else np.zeros((0, 8), dtype=np.float32)


def build_snapshot_aux_parquet(snapshot_dir: Path, *, workers: int = 24, log=print) -> Path:
    """Extract auxiliary trace metrics for a snapshot and write ``aux_labels.parquet``."""
    snapshot_dir = Path(snapshot_dir)
    out_path = snapshot_dir / 'aux_labels.parquet'
    if out_path.exists():
        log(json.dumps({'event': 'aux_labels_cached', 'path': str(out_path)}))
        return out_path

    manifest = json.loads((snapshot_dir / 'manifest.json').read_text(encoding='utf-8'))
    battles = pq.read_table(snapshot_dir / 'battles.parquet', columns=['job_id', 'source', 'finished_turn']).to_pandas()
    n_rows = len(battles)
    job_to_idx = {jid: i for i, jid in enumerate(battles['job_id'])}

    aux_matrix = np.full((n_rows, len(AUX_COLUMNS)), np.nan, dtype=np.float32)
    has_trace = np.zeros(n_rows, dtype=bool)

    for src in manifest['sources']:
        name = src['name']
        if not name.startswith('sim-'):
            continue
        db_path = Path(src['db']).resolve()
        if not db_path.exists():
            continue
        recover = bool(src.get('recover_invalid_rows', False))
        t0 = time.time()
        con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
        max_row = con.execute('SELECT rowid FROM jobs NOT INDEXED ORDER BY rowid DESC LIMIT 1').fetchone()
        con.close()
        if not max_row:
            continue
        max_rowid = int(max_row[0])
        n_chunks = max(workers * 4, 32)
        chunk_size = math.ceil(max_rowid / n_chunks)
        tasks = [
            (str(db_path), low, min(max_rowid, low + chunk_size - 1), recover)
            for low in range(1, max_rowid + 1, chunk_size)
        ]
        matched = 0
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for ids, vals in pool.map(_worker_scan_range, tasks):
                for jid, row_vals in zip(ids, vals):
                    idx = job_to_idx.get(jid)
                    if idx is not None:
                        aux_matrix[idx] = row_vals
                        has_trace[idx] = True
                        matched += 1
        log(json.dumps({
            'event': 'aux_source_extracted',
            'source': name,
            'matched_rows': matched,
            'elapsed_s': round(time.time() - t0, 1),
        }, ensure_ascii=False))

    table_dict = {
        'job_id': battles['job_id'].to_numpy(),
        'has_trace': has_trace,
    }
    for col_idx, col_name in enumerate(AUX_COLUMNS):
        table_dict[col_name] = aux_matrix[:, col_idx]

    tmp_path = out_path.with_suffix(f'.{os.getpid()}.tmp')
    pq.write_table(pa.table(table_dict), tmp_path, compression='snappy')
    tmp_path.replace(out_path)
    log(json.dumps({
        'event': 'aux_labels_written',
        'path': str(out_path),
        'total_rows': n_rows,
        'trace_rows': int(has_trace.sum()),
    }, ensure_ascii=False))
    return out_path
