"""On-the-fly combat step snapshot parser and multi-process streaming loader.

Every step in ``execution.trace`` contains a ``live`` state string (produced by
``ContinuationStamp.CaptureLive`` in C#) capturing the exact post-step state:
- Player state: ``turn``, ``hp``, ``max_hp``, ``block``, ``energy``, ``Y`` (cards/attacks played this turn)
- Player & Enemy active powers/statuses: ``P=<owner_combat_id>:<power_id>=<amount>/<turn_start_amt>[...]``
- Enemy states & intents: ``E0=<combat_id>/<monster_id>/<slot>/<hp>/<max_hp>/<block>/<move_id>``
- Card zones: ``H=`` (Hand), ``D=`` (Draw pile), ``C=`` (Discard pile), ``X=`` (Exhaust pile)
  with each card's live upgrade level, modified energy cost, Sly/Retain/Exhaust flags, and enchantments
- Active relic counters: ``relicCounters=<relic_id>/<cur>/<prev>,...``

From any non-terminal step snapshot ``(turn ti, step si)``, this module computes
on-the-fly the remaining-combat and current-turn supervision targets:
1. Primary outcomes (2):
   - ``rem_hp_loss_norm`` : ``clip((curr_hp - max(0, final_hp)) / max_hp, 0, 1)``
   - ``died``             : ``1.0`` if ``playerDied`` else ``0.0``
2. Remaining-combat per-turn process targets (9, matching ``AUX_COLUMNS`` + ``turns_norm``):
   - ``rem_turns_norm``           : ``log1p(T_rem)``
   - ``rem_dmg_per_turn``         : remaining damage dealt / ``T_rem``
   - ``rem_dmg_stability``        : future turn damage stability ``mean / (mean + std + 1e-5)``
   - ``rem_blk_per_turn``         : remaining block gained / ``T_rem``
   - ``rem_blk_stability``        : future non-lethal turn block stability
   - ``rem_eff_energy_gen``       : remaining effective energy available / ``T_rem``
   - ``rem_eff_energy_used``      : remaining effective energy spent / ``T_rem``
   - ``rem_extra_draw_per_turn``  : remaining extra cards drawn / ``T_rem``
   - ``rem_cards_per_turn``       : remaining cards played / ``T_rem``
3. Immediate current-turn & per-turn HP loss targets (4):
   - ``rem_hp_loss_per_turn``     : ``(curr_hp - max(0, final_hp)) / T_rem / 10.0``
   - ``this_turn_rem_dmg``        : remaining damage dealt in current turn ``ti`` ``/ 20.0``
   - ``this_turn_rem_blk``        : remaining block gained in current turn ``ti`` ``/ 20.0``
   - ``this_turn_hp_loss``        : HP lost at the end of current turn ``ti`` ``/ 15.0``
"""
from __future__ import annotations

import json
import math
import multiprocessing as mp
import queue
import random
import sqlite3
import time
import zlib
from pathlib import Path

import numpy as np

from .aux_labels import (
    AUX_COLUMNS,
    BLOCK_CARDS,
    INFINITE_HP,
    NUM_AUX_TARGETS,
    SHIV_GEN_CARDS,
    _extract_cost,
    _extract_int_var,
    _hp_lost,
)
from .features import PAD, TOKEN_NUMERICS, TOKEN_SLOTS, pad_tokens
from .role_priors import load_raw_cards

NUM_STEP_IMM_TARGETS = 4
STEP_IMM_TARGET_NAMES = (
    'rem_hp_loss_per_turn_div10',
    'this_turn_rem_dmg_div20',
    'this_turn_rem_blk_div20',
    'this_turn_hp_loss_div15',
)
NUM_HASH_BUCKETS = 512

ACT_NUM = {
    'OVERGROWTH': 1.0,
    'UNDERDOCKS': 1.0,
    'HIVE': 2.0,
    'GLORY': 3.0,
}

ZONE_CODE = {
    'hand': 1.0,
    'draw': 0.5,
    'discard': -0.5,
    'exhaust': -1.0,
}


def discover_trace_symbols(snapshot_dir: Path | str, sample_rows_per_db: int = 200) -> list[str]:
    """Quickly scan sample rows across ``sim-*`` SQLite DBs to collect common enemy/move/power symbols."""
    snapshot_dir = Path(snapshot_dir).resolve()
    manifest_path = snapshot_dir / 'manifest.json'
    extra: set[str] = set()

    # 1. Fixed structural symbols for step snapshots
    extra.update([
        'kind:global',
        'kind:card',
        'kind:relic',
        'kind:target',
        'upgrade:0',
        'upgrade:1',
        'ench:none',
        'mode:step',
        'kind:player_state',
        'kind:zone_summary',
        'kind:power',
        'kind:enemy',
        'owner:player',
        'owner:enemy',
        'zone:hand',
        'zone:draw',
        'zone:discard',
        'zone:exhaust',
        'cost:X',
        'cost:unplayable',
    ])
    for s in range(8):
        extra.add(f'slot:E{s}')
    for tb in range(16):
        extra.add(f'turn_bucket:{tb}')
    for e in range(13):
        extra.add(f'energy:{e}')
    for c in range(6):
        extra.add(f'cost:{c}')
        extra.add(f'cost:{c}:sly')
        extra.add(f'cost:{c}:ret')
    try:
        raw_cat_path = Path(__file__).resolve().parent.parent / 'catalogs/game-0.111.0.raw.json'
        if raw_cat_path.exists():
            raw_cat = json.loads(raw_cat_path.read_text(encoding='utf-8'))
            for c in raw_cat.get('cards', ()):
                extra.add(f"card:{c['id']}")
            for r in raw_cat.get('relics', ()):
                extra.add(f"relic:{r['id']}")
            for e in raw_cat.get('enchantments', ()):
                extra.add(f"ench:{e['id']}")
            for a in raw_cat.get('acts', ()):
                aid = a.get('id', '')
                for enc in a.get('encounters', ()):
                    extra.add(f"target:{aid}:{enc['id']}")
        else:
            for cid in load_raw_cards():
                extra.add(f'card:{cid}')
    except Exception:
        pass
    for h in range(NUM_HASH_BUCKETS):
        extra.add(f'step_hash:{h}')

    repo_trace_syms = Path(__file__).resolve().parent / 'trace_symbols.json'
    if repo_trace_syms.exists():
        try:
            extra.update(json.loads(repo_trace_syms.read_text(encoding='utf-8')))
        except Exception:
            pass
    snap_trace_syms = snapshot_dir / 'trace_symbols.json'
    if snap_trace_syms.exists():
        try:
            extra.update(json.loads(snap_trace_syms.read_text(encoding='utf-8')))
            return sorted(extra)
        except Exception:
            pass
    if not manifest_path.exists():
        return sorted(extra)

    manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
    for src in manifest.get('sources', ()):
        if not src.get('name', '').startswith('sim-'):
            continue
        db_path = Path(src['db'])
        if not db_path.exists():
            continue
        try:
            con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=10)
            max_row = con.execute('SELECT MAX(rowid) FROM jobs').fetchone()[0] or 0
            if max_row <= 0:
                con.close()
                continue
            # Sample evenly across beginning, middle, and end of the DB
            strides = [
                (1, min(max_row, sample_rows_per_db // 2)),
                (max(1, max_row // 2), min(max_row, max_row // 2 + sample_rows_per_db // 2)),
            ]
            for lo, hi in strides:
                rows = con.execute(
                    'SELECT result FROM jobs WHERE rowid BETWEEN ? AND ?',
                    (lo, hi),
                ).fetchall()
                for (raw,) in rows:
                    if not raw:
                        continue
                    try:
                        res = json.loads(raw)
                    except Exception:
                        continue
                    for t_obj in res.get('execution', {}).get('trace', ()):
                        for s in t_obj.get('deployment', {}).get('trace', ()):
                            live = s.get('live', '')
                            if not live or ';H=;D=;C=;X=;' in live:
                                continue
                            for part in live.split(';'):
                                if part.startswith('E') and '=' in part and not part.startswith('En'):
                                    k, v = part.split('=', 1)
                                    if k[1:].isdigit():
                                        f = v.split('/')
                                        if len(f) >= 7:
                                            eid, mid = f[1], f[6]
                                            extra.add(f'enemy:{eid}')
                                            extra.add(f'move:{mid}')
                                            extra.add(f'intent:{eid}:{mid}')
                                elif part.startswith('P='):
                                    for item in part[2:].split('],'):
                                        if ':' in item and '=' in item:
                                            pid = item.split(':', 1)[1].split('=', 1)[0]
                                            extra.add(f'power:{pid}')
            con.close()
        except Exception:
            pass
    return sorted(extra)


def augment_vocab_for_steps(vocab, snapshot_dir: Path | str | None = None) -> int:
    """Append step-snapshot symbols to ``vocab`` in-place without changing any existing index.

    Returns the symbol index of ``'zone:exhaust'``.
    """
    existing = set(vocab.spec['symbols'])
    new_syms = [s for s in discover_trace_symbols(snapshot_dir or Path('.')) if s not in existing]
    if new_syms:
        vocab.spec['symbols'] = list(vocab.spec['symbols']) + new_syms
        vocab.symbol_index = {k: i for i, k in enumerate(vocab.spec['symbols'])}
    return vocab.symbol_index.get('zone:exhaust', -1)


def _lookup_sym(sym: str, sym_idx: dict[str, int]) -> int:
    idx = sym_idx.get(sym)
    if idx is not None:
        return idx
    bucket = zlib.crc32(sym.encode('utf-8')) % NUM_HASH_BUCKETS
    return sym_idx.get(f'step_hash:{bucket}', 1)


def _parse_pile_cards(pile_str: str, zone_name: str, sym_idx: dict[str, int], out_tokens: list, max_cards: int = 30):
    if not pile_str:
        return 0
    z_sym = _lookup_sym(f'zone:{zone_name}', sym_idx)
    z_code = ZONE_CODE[zone_name]
    kind_card = sym_idx['kind:card']
    count = 0
    for item in pile_str.split('/baselib='):
        if not item:
            continue
        # Strip trailing "-," or modifier suffix from the previous item
        if item.startswith('-,'):
            item = item[2:]
        elif ',' in item and not item[0].isupper():
            comma = item.find(',')
            item = item[comma + 1 :]
        if not item or '/' not in item:
            continue
        count += 1
        if count > max_cards:
            continue
        parts = item.split('/')
        if len(parts) < 10:
            continue
        c_head = parts[0]
        plus = c_head.rfind('+')
        if plus > 0:
            cid = c_head[:plus]
            upg_str = c_head[plus + 1 :]
            upg = int(upg_str) if upg_str.isdigit() else 0
        else:
            cid, upg = c_head, 0

        cost_part = parts[1]
        costs_x = cost_part.startswith('True:')
        colon = cost_part.find(':')
        try:
            curr_cost = int(cost_part[colon + 1 :]) if colon >= 0 else 0
        except ValueError:
            curr_cost = 0

        is_sly = (parts[5] == 'True')
        should_retain = (parts[6] == 'True')

        ench_part = parts[9]
        if ench_part and not ench_part.startswith('-:'):
            ec = ench_part.split(':')
            ench_id = ec[0] if ec[0] != '-' else 'none'
            try:
                ench_amt = int(ec[1]) if len(ec) > 1 else 0
            except ValueError:
                ench_amt = 0
        else:
            ench_id, ench_amt = 'none', 0

        if costs_x:
            cost_tag = 'cost:X'
            cost_num = 0.5
        elif curr_cost < 0:
            cost_tag = 'cost:unplayable'
            cost_num = -0.25
        else:
            c_clamped = min(curr_cost, 5)
            suffix = ':sly' if is_sly else (':ret' if should_retain else '')
            cost_tag = f'cost:{c_clamped}{suffix}'
            cost_num = min(curr_cost, 6) / 4.0

        syms = (
            kind_card,
            _lookup_sym(f'card:{cid}', sym_idx),
            _lookup_sym(f'upgrade:{1 if upg > 0 else 0}', sym_idx),
            _lookup_sym(f'ench:{ench_id}', sym_idx),
            z_sym,
            _lookup_sym(cost_tag, sym_idx),
        )
        var_part = parts[10] if len(parts) > 10 else ''
        live_off, live_def = _parse_card_live_vars(var_part, cid, ench_amt)
        z_num = z_code + (0.25 if is_sly else 0.0) + (0.15 if should_retain else 0.0)
        nums = (live_off, live_def, cost_num, z_num)
        out_tokens.append((syms, nums))
    return count


def _parse_card_live_vars(var_part: str, cid: str, ench_amt: int) -> tuple[float, float]:
    """Extract normalized (live_offense, live_defense_utility) from ``-:0[Damage=19,Block=5,...]``."""
    lb = var_part.find('[')
    rb = var_part.rfind(']')
    if lb < 0 or rb <= lb + 1:
        return ench_amt / 10.0, 0.0
    inner = var_part[lb + 1 : rb]
    dmg = 0.0
    repeat = 1.0
    poison = 0.0
    shivs = 0.0
    vuln = 0.0
    off_pow = 0.0
    blk = 0.0
    weak = 0.0
    str_loss = 0.0
    cards_v = 0.0
    energy_v = 0.0
    def_pow = 0.0
    for kv in inner.split(','):
        if '=' not in kv:
            continue
        k, v_str = kv.split('=', 1)
        try:
            v = float(v_str)
        except ValueError:
            continue
        if k in ('Damage', 'CalculationBase', 'ExtraDamage'):
            dmg += v
        elif k == 'Repeat':
            repeat = max(1.0, v)
        elif k in ('PoisonPower', 'PoisonPerTurn'):
            poison += v
        elif k == 'Shivs':
            shivs += v
        elif k == 'VulnerablePower':
            vuln += v
        elif k in ('AccuracyPower', 'PhantomBladesPower', 'EnvenomPower', 'SerpentFormPower', 'Accelerant', 'Power'):
            off_pow += v
        elif k == 'Block':
            blk += v
        elif k == 'WeakPower':
            weak += v
        elif k == 'StrengthLoss':
            str_loss += v
        elif k in ('Cards', 'Skills'):
            if cid in SHIV_GEN_CARDS:
                shivs += v
            else:
                cards_v += v
        elif k == 'Energy':
            energy_v += v
        elif k in ('DexterityPower', 'Blur', 'AfterimagePower', 'ThornsPower'):
            def_pow += v
    off_val = (dmg * repeat + 1.5 * poison + 4.0 * shivs + 2.5 * vuln + 2.5 * off_pow) / 25.0
    def_val = (blk + 3.0 * weak + 1.5 * str_loss + 3.0 * cards_v + 5.0 * energy_v + 3.0 * def_pow) / 20.0 + (ench_amt / 10.0)
    return min(max(off_val, 0.0), 4.0), min(max(def_val, 0.0), 4.0)


def encode_live_step_tokens(
    live_str: str,
    act_id: str,
    target_id: str,
    init_relics: list[dict],
    sym_idx: dict[str, int],
) -> tuple[np.ndarray, np.ndarray] | None:
    """Parse one ``live`` state string into ``(symbols[T, 6], numerics[T, 4])`` arrays."""
    if not live_str or ';H=;D=;C=;X=;' in live_str:
        return None

    kv: dict[str, str] = {}
    enemies_raw: list[tuple[int, str]] = []
    for seg in live_str.split(';'):
        eq = seg.find('=')
        if eq < 0:
            continue
        k, v = seg[:eq], seg[eq + 1 :]
        if len(k) >= 2 and k[0] == 'E' and k[1:].isdigit():
            enemies_raw.append((int(k[1:]), v))
        else:
            kv[k] = v

    try:
        turn = int(kv.get('turn', '1'))
        curr_hp = int(kv.get('hp', '70'))
        max_hp = max(1, int(kv.get('max_hp', '70')))
        curr_blk = int(kv.get('block', '0'))
        curr_e = int(kv.get('energy', '0'))
    except ValueError:
        return None

    y_str = kv.get('Y', '0/0')
    y_slash = y_str.find('/')
    try:
        cards_played_turn = int(y_str[y_slash + 1 :]) if y_slash >= 0 else 0
    except ValueError:
        cards_played_turn = 0

    # Reserve first 3 slots for global, player_state, and zone_summary tokens
    token_list: list[tuple[tuple[int, ...], tuple[float, float, float, float]]] = [
        ((), (0.0, 0.0, 0.0, 0.0)),
        ((), (0.0, 0.0, 0.0, 0.0)),
        ((), (0.0, 0.0, 0.0, 0.0)),
    ]

    n_h = _parse_pile_cards(kv.get('H', ''), 'hand', sym_idx, token_list, max_cards=12)
    n_d = _parse_pile_cards(kv.get('D', ''), 'draw', sym_idx, token_list, max_cards=25)
    n_c = _parse_pile_cards(kv.get('C', ''), 'discard', sym_idx, token_list, max_cards=25)
    n_x = _parse_pile_cards(kv.get('X', ''), 'exhaust', sym_idx, token_list, max_cards=15)

    tb_sym = _lookup_sym(f'turn_bucket:{min(max(turn, 0), 15)}', sym_idx)
    act_num = ACT_NUM.get(act_id, 1.0)
    token_list[0] = (
        (sym_idx['kind:global'], _lookup_sym('mode:step', sym_idx), tb_sym, PAD, PAD, PAD),
        ((n_h + n_d + n_c) / 45.0, max_hp / 100.0, act_num / 3.0, curr_hp / float(max_hp)),
    )
    token_list[1] = (
        (
            _lookup_sym('kind:player_state', sym_idx),
            _lookup_sym(f'energy:{min(max(curr_e, 0), 12)}', sym_idx),
            tb_sym,
            PAD,
            PAD,
            PAD,
        ),
        (curr_blk / 50.0, curr_e / 5.0, turn / 15.0, n_h / 10.0),
    )
    token_list[2] = (
        (_lookup_sym('kind:zone_summary', sym_idx), PAD, PAD, PAD, PAD, PAD),
        (n_d / 30.0, n_c / 30.0, n_x / 20.0, cards_played_turn / 10.0),
    )

    # Relics + live relicCounters + mirrorRelics
    rc_map: dict[str, tuple[int, int]] = {}
    mr_str = kv.get('mirrorRelics', '')
    if mr_str:
        for mr_item in mr_str.split(','):
            mr_parts = mr_item.split('/')
            if len(mr_parts) >= 2:
                try:
                    rc_map[mr_parts[0]] = (int(mr_parts[1]), 0)
                except ValueError:
                    pass
    rc_str = kv.get('relicCounters', '')
    if rc_str:
        for rc_item in rc_str.split(','):
            rc_parts = rc_item.split('/')
            if len(rc_parts) >= 3:
                try:
                    rc_map[rc_parts[0]] = (int(rc_parts[1]), int(rc_parts[2]))
                except ValueError:
                    pass

    kind_relic = sym_idx['kind:relic']
    n_rel = max(1, len(init_relics))
    for r_idx, rel in enumerate(init_relics):
        rid = rel.get('id', '')
        if not rid:
            continue
        rc_cur, rc_prev = rc_map.get(rid, (0, 0))
        token_list.append((
            (kind_relic, _lookup_sym(f'relic:{rid}', sym_idx), PAD, PAD, PAD, PAD),
            (rc_cur / 10.0, rc_prev / 10.0, (r_idx + 1) / float(n_rel), 0.0),
        ))

    # Enemies + AI move history (AI0..AI7) + Monster state counter (MS0..MS7)
    kind_enemy = _lookup_sym('kind:enemy', sym_idx)
    combat_id_to_enemy: dict[int, tuple[int, str, int]] = {}
    for e_slot, e_val in enemies_raw[:8]:
        f = e_val.split('/')
        if len(f) < 7:
            continue
        try:
            ecid = int(f[0])
            ehp = int(f[3])
            emhp = max(1, int(f[4]))
            eblk = int(f[5])
        except ValueError:
            continue
        if ehp <= 0 or ehp >= INFINITE_HP:
            continue
        eid, mid = f[1], f[6]
        combat_id_to_enemy[ecid] = (e_slot, eid, ehp)
        ai_moves = [m for m in kv.get(f'AI{e_slot}', '').split(',') if m and m != '-']
        if len(ai_moves) >= 2:
            prev_move_sym = _lookup_sym(f'move:{ai_moves[-2]}', sym_idx)
        elif len(ai_moves) == 1:
            prev_move_sym = _lookup_sym(f'move:{ai_moves[0]}', sym_idx)
        else:
            prev_move_sym = PAD
        ms_raw = kv.get(f'MS{e_slot}', '')
        ms_cnt = 0
        if '/' in ms_raw:
            try:
                ms_cnt = int(ms_raw.rsplit('/', 1)[-1])
            except ValueError:
                ms_cnt = 0
        token_list.append((
            (
                kind_enemy,
                _lookup_sym(f'enemy:{eid}', sym_idx),
                _lookup_sym(f'intent:{eid}:{mid}', sym_idx),
                _lookup_sym(f'move:{mid}', sym_idx),
                _lookup_sym(f'slot:E{min(e_slot, 7)}', sym_idx),
                prev_move_sym,
            ),
            (ehp / 100.0, emhp / 100.0, ehp / float(emhp), eblk / 50.0 + 0.1 * ms_cnt),
        ))

    # Powers (Player = 0, Enemies = combat_id) + bracket modifiers
    p_str = kv.get('P', '')
    if p_str:
        kind_power = _lookup_sym('kind:power', sym_idx)
        owner_player = _lookup_sym('owner:player', sym_idx)
        owner_enemy = _lookup_sym('owner:enemy', sym_idx)
        for p_item in p_str.split('],'):
            if not p_item or ':' not in p_item or '=' not in p_item:
                continue
            if '[' in p_item:
                head, br_part = p_item.split('[', 1)
            else:
                head, br_part = p_item, ''
            c_pos = head.find(':')
            eq_pos = head.find('=', c_pos)
            if c_pos < 0 or eq_pos < 0:
                continue
            try:
                owner_cid = int(head[:c_pos])
            except ValueError:
                continue
            pid = head[c_pos + 1 : eq_pos]
            amt_part = head[eq_pos + 1 :]
            sl_pos = amt_part.find('/')
            try:
                amt = int(amt_part[:sl_pos]) if sl_pos >= 0 else int(amt_part)
                ts_amt = int(amt_part[sl_pos + 1 :]) if sl_pos >= 0 else 0
            except ValueError:
                amt, ts_amt = 1, 0
            p_mod = 0.0
            if br_part:
                for p_kv in br_part.split(','):
                    if '=' not in p_kv:
                        continue
                    pk, pv_s = p_kv.split('=', 1)
                    try:
                        pv = float(pv_s)
                    except ValueError:
                        continue
                    if pk == 'DamageIncrease':
                        p_mod += (pv - 1.0)
                    elif pk == 'DamageDecrease':
                        p_mod -= (1.0 - pv)
                    elif pk in ('Block', 'StrengthPower', 'SlowAmount', 'CardsLeft', 'Damage'):
                        p_mod += pv / 10.0
            log_amt = math.copysign(math.log1p(abs(amt)), amt)
            p_sym = _lookup_sym(f'power:{pid}', sym_idx)
            if owner_cid == 0:
                token_list.append((
                    (kind_power, owner_player, p_sym, PAD, PAD, PAD),
                    (amt / 10.0, log_amt / 3.0, ts_amt / 10.0 + p_mod, 1.0 if amt > 0 else -1.0),
                ))
            elif owner_cid in combat_id_to_enemy:
                e_slot, eid, ehp = combat_id_to_enemy[owner_cid]
                token_list.append((
                    (
                        kind_power,
                        owner_enemy,
                        p_sym,
                        _lookup_sym(f'enemy:{eid}', sym_idx),
                        _lookup_sym(f'slot:E{min(e_slot, 7)}', sym_idx),
                        PAD,
                    ),
                    (amt / 20.0, log_amt / 4.0, ts_amt / 20.0 + p_mod, ehp / 100.0),
                ))

    # Target token
    token_list.append((
        (sym_idx['kind:target'], _lookup_sym(f'target:{act_id}:{target_id}', sym_idx), PAD, PAD, PAD, PAD),
        (0.0, 0.0, 0.0, 0.0),
    ))

    n_tok = len(token_list)
    symbols = np.zeros((n_tok, TOKEN_SLOTS), dtype=np.int32)
    numerics = np.zeros((n_tok, TOKEN_NUMERICS), dtype=np.float32)
    for ti, (s_tup, n_tup) in enumerate(token_list):
        symbols[ti, : len(s_tup)] = s_tup
        numerics[ti] = n_tup
    return symbols, numerics


def extract_battle_step_samples(
    raw_json: str,
    act_id: str,
    target_id: str,
    weight: float,
    sym_idx: dict[str, int],
    aux_mu: np.ndarray,
    aux_sd: np.ndarray,
    *,
    max_steps_per_battle: int = 3,
    rng: random.Random | None = None,
) -> list[tuple[np.ndarray, np.ndarray, float, float, np.ndarray, np.ndarray, float]]:
    """Parse one battle's ``result`` JSON and return up to ``max_steps_per_battle`` step samples.

    Each returned item is:
        ``(symbols[T, 6], numerics[T, 4], y_norm, died, aux_y[9], imm_y[4], step_weight)``
    """
    try:
        res = json.loads(raw_json)
    except Exception:
        return []
    obs = res.get('trainingObservation')
    ex = res.get('execution')
    if not obs or not ex:
        return []
    trace = ex.get('trace')
    if not trace:
        return []

    total_turns = res.get('finishedTurn') or len(trace)
    if total_turns <= 0:
        total_turns = len(trace)
    player_died = bool(obs.get('playerDied'))
    final_hp = max(0, int(obs.get('finalHp', 0)))
    init_build = obs.get('initialBuild') or {}
    init_relics = init_build.get('relics') or []
    relic_ids = {r.get('id', '') for r in init_relics}
    has_ice_cream = 'ICE_CREAM' in relic_ids
    has_orichalcum = 'ORICHALCUM' in relic_ids
    has_cloak_clasp = 'CLOAK_CLASP' in relic_ids
    has_ninja_scroll = 'NINJA_SCROLL' in relic_ids

    n_turns = len(trace)
    step_dmgs: list[list[float]] = []
    step_blks: list[list[float]] = []
    step_e_used: list[list[float]] = []
    step_cards: list[list[float]] = []
    step_ex_draw: list[list[float]] = []
    step_hps: list[list[int]] = []
    step_max_hps: list[list[int]] = []
    step_energies: list[list[int]] = []
    step_lives: list[list[str]] = []

    turn_dmgs: list[float] = []
    turn_blks: list[float] = []
    turn_e_gen: list[float] = []
    turn_end_blk: list[float] = []
    turn_end_poison_dmg: list[float] = [0.0] * n_turns

    enemy_max_hp: dict[int, int] = {}
    enemy_last_hp: dict[int, int] = {}
    prev_enemies: dict[int, tuple[int, int, int]] = {}

    retained_from_prev_turn = 0
    prev_inf_blades = 0
    prev_tools_power = 0
    prev_end_energy = 0

    for ti, t_obj in enumerate(trace):
        t = t_obj.get('turn', ti + 1)
        steps = t_obj.get('deployment', {}).get('trace') or []
        if not steps:
            turn_gen = 3.0
            turn_e_gen.append(turn_gen)
            prev_end_energy = (prev_end_energy + 3) if has_ice_cream else 0
            retained_from_prev_turn = 0
            step_dmgs.append([])
            step_blks.append([])
            step_e_used.append([])
            step_cards.append([])
            step_ex_draw.append([])
            step_hps.append([])
            step_max_hps.append([])
            step_energies.append([])
            step_lives.append([])
            turn_dmgs.append(0.0)
            turn_blks.append(0.0)
            turn_end_blk.append(0.0)
            continue

        s_dmg_list: list[float] = []
        s_blk_list: list[float] = []
        s_eu_list: list[float] = []
        s_cp_list: list[float] = []
        s_ed_list: list[float] = []
        s_hp_list: list[int] = []
        s_mhp_list: list[int] = []
        s_e_list: list[int] = []
        s_live_list: list[str] = []

        prev_block = 0
        prev_H_len = 0
        turn_drawn = 0
        turn_spent = 0
        turn_sly_e = 0
        prev_e = None

        for si, s in enumerate(steps):
            act = s.get('action') or {}
            live_str = s.get('live', '')
            cid = act.get('CardId', '')
            csk = act.get('CardStateKey', '')

            hp_pos = live_str.find(';hp=')
            cur_hp = int(live_str[hp_pos + 4 : live_str.find(';', hp_pos + 4)]) if hp_pos >= 0 else 70
            mhp_pos = live_str.find(';max_hp=')
            cur_mhp = int(live_str[mhp_pos + 8 : live_str.find(';', mhp_pos + 8)]) if mhp_pos >= 0 else 70
            blk_pos = live_str.find(';block=')
            cur_block = int(live_str[blk_pos + 7 : live_str.find(';', blk_pos + 7)]) if blk_pos >= 0 else 0
            eng_pos = live_str.find(';energy=')
            curr_e = int(live_str[eng_pos + 8 : live_str.find(';', eng_pos + 8)]) if eng_pos >= 0 else 0

            is_x, cost = _extract_cost(csk)
            if is_x:
                cost = max(0, (prev_e if prev_e is not None else 3) - curr_e)

            step_played = 1 if cid else 0
            step_spent = cost if cid else 0
            turn_spent += step_spent

            choice = act.get('Choice')
            disc_cnt = 0
            step_sly_cnt = 0
            step_sly_cost = 0
            if choice and choice.get('Cards') and choice.get('SourcePile') == 2:
                cards_c = choice['Cards']
                disc_cnt = len(cards_c)
                for cc in cards_c:
                    sk = cc.get('StateKey', '')
                    if '|sly=True|' in sk and cc.get('CardId') not in ('REFLEX', 'TACTICIAN'):
                        step_sly_cnt += 1
                        _, scost = _extract_cost(sk)
                        step_sly_cost += scost
            turn_sly_e += step_sly_cost

            this_dmg = 0.0
            this_blk = 0.0
            this_ex_draw = 0.0

            combat_over = ';H=;D=;C=;X=;' in live_str
            if not combat_over:
                if cur_block > prev_block:
                    this_blk += float(cur_block - prev_block)
                prev_block = cur_block

                h_pos = live_str.find(';H=')
                h_end = live_str.find(';D=', h_pos) if h_pos >= 0 else -1
                h_str = live_str[h_pos + 3 : h_end] if (h_pos >= 0 and h_end >= 0) else ''
                curr_H_len = h_str.count('/baselib=')
                gen_shivs = 0
                if cid in SHIV_GEN_CARDS:
                    gen_shivs = _extract_int_var(csk, 'Shivs=') or _extract_int_var(csk, 'Cards=')

                if si == 0:
                    start_gen = prev_inf_blades + (3 if (t == 1 and has_ninja_scroll) else 0)
                    drawn_now = max(0, curr_H_len + step_played + disc_cnt + prev_tools_power - retained_from_prev_turn - start_gen - gen_shivs)
                    this_ex_draw = float(max(0, drawn_now - 5))
                else:
                    drawn_now = max(0, curr_H_len - (prev_H_len - step_played - disc_cnt + gen_shivs))
                    this_ex_draw = float(drawn_now)
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
                                    lost = _hp_lost(p_ehp, ehp)
                                    if si == 0 and ti > 0:
                                        if lost:
                                            # Enemy-turn poison/thorns damage between turn ti-1 and ti
                                            turn_end_poison_dmg[ti - 1] += float(lost)
                                    else:
                                        this_dmg += float(lost)
                                        if eblk < p_eblk:
                                            this_dmg += float(p_eblk - eblk)
                                else:
                                    this_dmg += float(_hp_lost(emhp, ehp))
                                enemy_last_hp[ecid] = ehp
                    for pecid, (p_ehp, _, p_eblk) in prev_enemies.items():
                        if pecid not in cur_enemies and enemy_last_hp.get(pecid, 0) > 0:
                            last = enemy_last_hp[pecid]
                            if last < INFINITE_HP:
                                killed_dmg = float(last + (p_eblk if si > 0 else 0))
                                if si == 0 and ti > 0:
                                    turn_end_poison_dmg[ti - 1] += killed_dmg
                                else:
                                    this_dmg += killed_dmg
                            enemy_last_hp[pecid] = 0
                    prev_enemies = cur_enemies
            else:
                if cid in BLOCK_CARDS:
                    this_blk += float(_extract_int_var(csk, 'Block='))
                if si == 0:
                    this_ex_draw = float(max(0, prev_tools_power))

            prev_e = curr_e
            s_dmg_list.append(this_dmg)
            s_blk_list.append(this_blk)
            s_eu_list.append(float(step_spent + step_sly_cost))
            s_cp_list.append(float(step_played + step_sly_cnt))
            s_ed_list.append(this_ex_draw)
            s_hp_list.append(cur_hp)
            s_mhp_list.append(cur_mhp)
            s_e_list.append(curr_e)
            s_live_list.append('' if combat_over else live_str)

        last_live = steps[-1].get('live', '')
        combat_over = ';H=;D=;C=;X=;' in last_live
        eng_pos = last_live.find(';energy=')
        end_e = int(last_live[eng_pos + 8 : last_live.find(';', eng_pos + 8)]) if eng_pos >= 0 else 0
        carry = prev_end_energy if has_ice_cream else 0
        turn_gen = float(max(0, turn_spent + end_e - carry) + turn_sly_e)
        turn_e_gen.append(turn_gen)
        prev_end_energy = end_e

        end_relic_b = 0.0
        if not combat_over:
            if has_orichalcum and prev_block == 0:
                end_relic_b += 6.0
            h_pos = last_live.find(';H=')
            h_end = last_live.find(';D=', h_pos) if h_pos >= 0 else -1
            h_str = last_live[h_pos + 3 : h_end] if (h_pos >= 0 and h_end >= 0) else ''
            end_h_len = h_str.count('/baselib=')
            if has_cloak_clasp:
                end_relic_b += float(end_h_len)

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

        turn_end_blk.append(end_relic_b)
        step_dmgs.append(s_dmg_list)
        step_blks.append(s_blk_list)
        step_e_used.append(s_eu_list)
        step_cards.append(s_cp_list)
        step_ex_draw.append(s_ed_list)
        step_hps.append(s_hp_list)
        step_max_hps.append(s_mhp_list)
        step_energies.append(s_e_list)
        step_lives.append(s_live_list)
        turn_dmgs.append(sum(s_dmg_list))
        turn_blks.append(sum(s_blk_list) + end_relic_b)

    # Add enemy-turn poison/thorns damage to the turn that preceded it
    for ti in range(n_turns):
        if turn_end_poison_dmg[ti] > 0:
            turn_dmgs[ti] += turn_end_poison_dmg[ti]

    # Add killing blow remaining HP to the last step of the last turn
    if not player_died and step_dmgs and step_dmgs[-1]:
        rem_enemy_hp = float(sum(hp for hp in enemy_last_hp.values() if 0 < hp < INFINITE_HP))
        step_dmgs[-1][-1] += rem_enemy_hp
        turn_dmgs[-1] += rem_enemy_hp

    # Candidate non-terminal steps (ti, si)
    candidates: list[tuple[int, int]] = []
    for ti in range(n_turns):
        for si, lstr in enumerate(step_lives[ti]):
            if lstr:
                candidates.append((ti, si))
    if not candidates:
        return []

    if len(candidates) > max_steps_per_battle:
        if rng is not None:
            chosen = rng.sample(candidates, max_steps_per_battle)
        else:
            chosen = random.sample(candidates, max_steps_per_battle)
    else:
        chosen = candidates

    out_samples = []
    step_w = float(weight) / max(1, len(chosen))

    for ti, si in chosen:
        live_str = step_lives[ti][si]
        encoded = encode_live_step_tokens(live_str, act_id, target_id, init_relics, sym_idx)
        if encoded is None:
            continue
        syms, nums = encoded

        curr_hp = step_hps[ti][si]
        curr_mhp = max(1, step_max_hps[ti][si])
        curr_e = step_energies[ti][si]

        n_steps_ti = len(step_lives[ti])
        frac_turn_left = ((n_steps_ti - 1 - si) + 0.5) / (n_steps_ti + 0.5)
        t_rem = max(0.5, (n_turns - 1 - ti) + frac_turn_left)
        inv_t_rem = 1.0 / t_rem

        # Immediate outcomes in current turn ti (after step si)
        this_turn_rem_dmg = sum(step_dmgs[ti][si + 1 :]) + turn_end_poison_dmg[ti]
        this_turn_rem_blk = sum(step_blks[ti][si + 1 :]) + turn_end_blk[ti]
        next_hp = step_hps[ti + 1][0] if (ti + 1 < n_turns and step_hps[ti + 1]) else final_hp
        this_turn_hp_loss = max(0.0, float(curr_hp - next_hp))

        # Remaining-combat totals from after step (ti, si) to the end of turn n_turns - 1
        rem_dmg = this_turn_rem_dmg + sum(turn_dmgs[ti + 1 :])
        rem_blk = this_turn_rem_blk + sum(turn_blks[ti + 1 :])
        rem_eu_ti = sum(step_e_used[ti][si + 1 :])
        rem_eu = rem_eu_ti + sum(sum(x) for x in step_e_used[ti + 1 :])
        rem_eg_ti = float(curr_e) + max(0.0, rem_eu_ti - float(curr_e))
        rem_eg = rem_eg_ti + sum(turn_e_gen[ti + 1 :])
        rem_ed = sum(step_ex_draw[ti][si + 1 :]) + sum(sum(x) for x in step_ex_draw[ti + 1 :])
        rem_cp = sum(step_cards[ti][si + 1 :]) + sum(sum(x) for x in step_cards[ti + 1 :])

        # Remaining turn-level damage & block stability
        rem_turn_dmgs = [this_turn_rem_dmg / max(frac_turn_left, 0.25)] + turn_dmgs[ti + 1 :]
        d_mean = sum(rem_turn_dmgs) / len(rem_turn_dmgs)
        d_std = math.sqrt(sum((x - d_mean) ** 2 for x in rem_turn_dmgs) / len(rem_turn_dmgs)) if len(rem_turn_dmgs) > 1 else 0.0
        rem_dmg_stab = d_mean / (d_mean + d_std + 1e-5)

        rem_turn_blks = [this_turn_rem_blk / max(frac_turn_left, 0.25)] + turn_blks[ti + 1 :]
        surv_blks = rem_turn_blks[:-1] if (not player_died and len(rem_turn_blks) > 1) else rem_turn_blks
        b_mean = sum(surv_blks) / len(surv_blks) if surv_blks else 0.0
        b_std = math.sqrt(sum((x - b_mean) ** 2 for x in surv_blks) / len(surv_blks)) if len(surv_blks) > 1 else 0.0
        rem_blk_stab = b_mean / (b_mean + b_std + 1e-5)

        raw_aux = np.array([
            math.log1p(t_rem),
            rem_dmg * inv_t_rem,
            rem_dmg_stab,
            rem_blk * inv_t_rem,
            rem_blk_stab,
            rem_eg * inv_t_rem,
            rem_eu * inv_t_rem,
            rem_ed * inv_t_rem,
            rem_cp * inv_t_rem,
        ], dtype=np.float32)
        z_aux = (raw_aux - aux_mu) / aux_sd

        rem_hp_loss = max(0.0, float(curr_hp - final_hp))
        y_norm = float(np.clip(rem_hp_loss / float(curr_mhp), 0.0, 1.0))
        died_val = 1.0 if player_died else 0.0

        imm_y = np.array([
            (rem_hp_loss * inv_t_rem) / 10.0,
            this_turn_rem_dmg / 20.0,
            this_turn_rem_blk / 20.0,
            this_turn_hp_loss / 15.0,
        ], dtype=np.float32)

        out_samples.append((syms, nums, y_norm, died_val, z_aux, imm_y, step_w))

    return out_samples


# Global read-only state shared via fork COW with worker processes
_WORKER_STATE: dict = {}


def _emit_batch_from_reservoir(reservoir: list, batch_size: int, rng: random.Random):
    chosen = rng.sample(reservoir, batch_size) if len(reservoir) >= batch_size else [rng.choice(reservoir) for _ in range(batch_size)]
    parts = [(s[0], s[1]) for s in chosen]
    b_syms, b_nums, _ = pad_tokens(parts)
    return (
        b_syms.astype(np.int64),
        b_nums,
        np.asarray([s[2] for s in chosen], dtype=np.float32),
        np.asarray([s[3] for s in chosen], dtype=np.float32),
        np.stack([s[4] for s in chosen], axis=0),
        np.stack([s[5] for s in chosen], axis=0),
        np.asarray([s[6] for s in chosen], dtype=np.float32),
    )


def _stream_worker_loop(worker_id: int, num_workers: int, out_queue: mp.Queue, stop_event, seed: int):
    rng = random.Random(seed + worker_id * 10007)
    db_ranges = list(_WORKER_STATE['db_ranges'])
    sym_idx = _WORKER_STATE['sym_idx']
    job_meta = _WORKER_STATE['job_meta']
    aux_mu = _WORKER_STATE['aux_mu']
    aux_sd = _WORKER_STATE['aux_sd']
    batch_size = _WORKER_STATE['batch_size']
    max_steps = _WORKER_STATE['max_steps_per_battle']
    block_rows = _WORKER_STATE['chunk_size']
    reservoir_cap = 49152
    min_ready = min(batch_size, 512)

    if not db_ranges:
        return
    my_dbs = db_ranges[worker_id::num_workers]
    if not my_dbs:
        my_dbs = [db_ranges[worker_id % len(db_ranges)]]

    # Maintain one sequential cursor per assigned DB starting at a random offset
    cursors = []
    for db_path, min_r, max_r in my_dbs:
        span = max(1, max_r - min_r + 1)
        offset = min_r + ((rng.randint(0, span - 1) + worker_id * (span // max(1, num_workers))) % span)
        cursors.append([db_path, min_r, max_r, offset])

    reservoir: list = []
    con_cache: dict[str, sqlite3.Connection] = {}
    db_turn = 0
    import os
    parent_pid = _WORKER_STATE.get('parent_pid', 0)
    try:
        while not stop_event.is_set():
            if parent_pid and os.getppid() != parent_pid:
                break
            db_path, min_r, max_r, cur = cursors[db_turn % len(cursors)]
            db_turn += 1
            hi = min(max_r, cur + block_rows - 1)
            next_cur = min_r if hi >= max_r else (hi + 1)
            cursors[(db_turn - 1) % len(cursors)][3] = next_cur

            con = con_cache.get(db_path)
            if con is None:
                con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
                con.execute('PRAGMA query_only=ON')
                con.execute('PRAGMA cache_size=-16384')
                con_cache[db_path] = con
            try:
                rows = con.execute(
                    'SELECT id, status, result FROM jobs WHERE rowid BETWEEN ? AND ?',
                    (cur, hi),
                ).fetchall()
            except Exception:
                continue

            for jid, status, raw in rows:
                if status != 'complete' or not raw:
                    continue
                meta = job_meta.get(jid)
                if meta is None:
                    continue
                act_id, target_id, w = meta
                samples = extract_battle_step_samples(
                    raw, act_id, target_id, w, sym_idx, aux_mu, aux_sd,
                    max_steps_per_battle=max_steps, rng=rng,
                )
                for item in samples:
                    if len(reservoir) < reservoir_cap:
                        reservoir.append(item)
                    else:
                        reservoir[rng.randrange(reservoir_cap)] = item

            if len(reservoir) >= min_ready:
                # Emit randomized batches per sequential SQLite block, backpressuring on out_queue
                # so workers never spin-read SQLite while the GPU consumer queue is full.
                n_emit = 16 if len(reservoir) >= batch_size * 4 else (8 if len(reservoir) >= batch_size * 2 else 3)
                for _ in range(n_emit):
                    if stop_event.is_set():
                        break
                    batch_tuple = _emit_batch_from_reservoir(reservoir, batch_size, rng)
                    while not stop_event.is_set():
                        try:
                            out_queue.put(batch_tuple, timeout=0.1)
                            break
                        except queue.Full:
                            continue
    finally:
        for c in con_cache.values():
            try:
                c.close()
            except Exception:
                pass


class StepBatchStreamer:
    """Background multi-process streamer producing on-the-fly in-combat step batches from SQLite."""

    def __init__(
        self,
        dataset,
        aux_mu: np.ndarray,
        aux_sd: np.ndarray,
        *,
        batch_size: int = 1024,
        max_steps_per_battle: int = 6,
        num_workers: int = 8,
        chunk_size: int = 256,
        seed: int = 20260911,
    ):
        self.batch_size = batch_size
        self.num_workers = num_workers
        self.seed = seed

        manifest = dataset.snapshot.manifest
        sim_sources = {s['name']: s['db'] for s in manifest.get('sources', ()) if s['name'].startswith('sim-')}

        # Only include training-split rows to guarantee zero leakage into validation/test
        train_rows = dataset.split_rows('train')
        sim_mask = train_rows['source'].isin(sim_sources.keys())
        sim_train = train_rows[sim_mask]

        job_meta: dict[str, tuple[str, str, float]] = {}
        for jid, act_id, target_id, w in zip(
            sim_train['job_id'], sim_train['act_id'], sim_train['target_id'], sim_train['weight']
        ):
            job_meta[jid] = (act_id, target_id, float(w))

        db_ranges: list[tuple[str, int, int]] = []
        n_chunks = 0
        for sname, db_path in sim_sources.items():
            if not Path(db_path).exists():
                continue
            try:
                con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=15)
                min_r = con.execute('SELECT MIN(rowid) FROM jobs').fetchone()[0]
                max_r = con.execute('SELECT MAX(rowid) FROM jobs').fetchone()[0]
                con.close()
                if min_r is not None and max_r is not None:
                    db_ranges.append((str(db_path), int(min_r), int(max_r)))
                    n_chunks += (int(max_r) - int(min_r) + chunk_size) // chunk_size
            except Exception:
                pass

        self.n_train_trace_battles = len(job_meta)
        self.n_chunks = n_chunks

        global _WORKER_STATE
        import os
        _WORKER_STATE = {
            'parent_pid': os.getpid(),
            'db_ranges': db_ranges,
            'sym_idx': dict(dataset.vocab.symbol_index),
            'job_meta': job_meta,
            'aux_mu': np.asarray(aux_mu, dtype=np.float32),
            'aux_sd': np.asarray(aux_sd, dtype=np.float32),
            'batch_size': int(batch_size),
            'max_steps_per_battle': int(max_steps_per_battle),
            'chunk_size': int(chunk_size),
        }

        self._sync_gen = None
        if num_workers <= 0:
            self.queue = None
            self.stop_event = None
            self.workers = []
            self._sync_gen = self._make_sync_generator()
        else:
            ctx = mp.get_context('fork')
            self.queue = ctx.Queue(maxsize=max(16, num_workers * 3))
            self.queue.cancel_join_thread()
            self.stop_event = ctx.Event()
            self.workers = []
            for wid in range(num_workers):
                p = ctx.Process(
                    target=_stream_worker_loop,
                    args=(wid, num_workers, self.queue, self.stop_event, seed),
                    daemon=True,
                )
                p.start()
                self.workers.append(p)

    def _make_sync_generator(self):
        st = _WORKER_STATE
        rng = random.Random(self.seed)
        db_ranges = st['db_ranges']
        sym_idx = st['sym_idx']
        job_meta = st['job_meta']
        aux_mu = st['aux_mu']
        aux_sd = st['aux_sd']
        batch_size = st['batch_size']
        max_steps = st['max_steps_per_battle']
        chunk_size = st['chunk_size']
        conns = {
            db_path: sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=30)
            for db_path, _, _ in db_ranges
        }
        buf = []
        while True:
            db_path, min_r, max_r = rng.choice(db_ranges)
            lo = rng.randint(min_r, max(min_r, max_r - chunk_size + 1))
            hi = min(max_r, lo + chunk_size - 1)
            rows = conns[db_path].execute(
                'SELECT id, result FROM jobs WHERE rowid BETWEEN ? AND ?',
                (lo, hi),
            ).fetchall()
            rng.shuffle(rows)
            for jid, raw_json in rows:
                meta = job_meta.get(jid)
                if meta is None or not raw_json:
                    continue
                act_id, target_id, w = meta
                samples = extract_battle_step_samples(
                    raw_json, act_id, target_id, w, sym_idx, aux_mu, aux_sd,
                    max_steps_per_battle=max_steps, rng=rng,
                )
                buf.extend(samples)
                if len(buf) >= batch_size:
                    yield _emit_batch_from_reservoir(buf, batch_size, rng)
                    if len(buf) > batch_size * 4:
                        del buf[:batch_size]

    def next_batch(self, device):
        import torch
        if self._sync_gen is not None:
            b_syms, b_nums, b_y, b_died, b_aux, b_imm, b_w = next(self._sync_gen)
        else:
            b_syms, b_nums, b_y, b_died, b_aux, b_imm, b_w = self.queue.get()
        return (
            torch.from_numpy(b_syms).to(device, non_blocking=True),
            torch.from_numpy(b_nums).to(device, non_blocking=True),
            torch.from_numpy(b_y).to(device, non_blocking=True),
            torch.from_numpy(b_died).to(device, non_blocking=True),
            torch.from_numpy(b_aux).to(device, non_blocking=True),
            torch.from_numpy(b_imm).to(device, non_blocking=True),
            torch.from_numpy(b_w).to(device, non_blocking=True),
        )

    def close(self):
        if self.stop_event is not None:
            self.stop_event.set()
        for p in self.workers:
            if p.is_alive():
                p.terminate()
        for p in self.workers:
            p.join(timeout=1.0)
        if self.queue is not None:
            try:
                self.queue.close()
            except Exception:
                pass
