"""Per-token domain role priors and deck-conditioned per-token context interactions.

Each card and relic token receives:
1. A 16-dim deterministic role vector aligned with its identity and upgrade level:
   - [0]  cost_norm        (card energy cost / 3.0; 0 for unplayable/relics)
   - [1]  is_attack        (1.0 for Attack cards)
   - [2]  is_skill         (1.0 for Skill cards)
   - [3]  is_power         (1.0 for Power cards)
   - [4]  is_clutter       (1.0 for Status / Curse / Quest unplayable cards)
   - [5]  terminal_w       (terminal / win-condition weight)
   - [6]  draw_w           (draw / cycle / deck manipulation weight)
   - [7]  energy_w         (energy generation / cost reduction weight)
   - [8]  scaling_w        (long-term stat / engine scaling weight)
   - [9]  mitigation_w     (block / weak / damage reduction weight)
   - [10] shiv_source      (shiv generation weight)
   - [11] shiv_payoff      (shiv / multi-play scaling payoff weight)
   - [12] poison_source    (poison application weight)
   - [13] poison_payoff    (poison multiplier / trigger / payoff weight)
   - [14] discard_source   (active discard trigger weight)
   - [15] discard_payoff   (Sly / discard payoff weight)

2. An 8-dim dynamic per-token context vector computed on the fly in GPU from
   the interaction between the token's own role/cost/synergy needs and the
   rest of the deck's supply (excluding self where appropriate).
"""
from __future__ import annotations

import json
from pathlib import Path
import numpy as np
import torch

from . import ROOT

PRIOR_DIM = 16
CONTEXT_DIM = 8

# Upgraded cost overrides where upgrading changes energy cost in game 0.111.0.
UPGRADED_COST_OVERRIDES = {
    'MURDER': 2,
    'WELL_LAID_PLANS': 1,
    'TRACKING': 1,
    'MASTER_PLANNER': 1,
    'TOOLS_OF_THE_TRADE': 0,
    'MIRAGE': 0,
    'SHADOWMELD': 0,
    'SHADOW_STEP': 0,
    'BULLET_TIME': 2,
    'NIGHTMARE': 2,
    'AUTOMATION': 0,
    'MIND_BLAST': 0,
    'STRATAGEM': 0,
    'CALAMITY': 2,
    'MAYHEM': 1,
    'NOSTALGIA': 0,
    'APOTHEOSIS': 1,
    'DISTRACTION': 0,
    'ENTRENCH': 1,
}

# (unupgraded, upgraded) weights for each per-card concept dimension.
CARD_TERMINAL_PRIORS = {
    # Primary Silent terminals (0.5)
    'SERPENT_FORM': (0.50, 0.55),
    'NOXIOUS_FUMES': (0.50, 0.55),
    'ACCELERANT': (0.50, 0.60),
    'OUTBREAK': (0.50, 0.55),
    'KNIFE_TRAP': (0.50, 0.60),
    # Secondary Silent terminals (0.3)
    'ACCURACY': (0.30, 0.35),
    'GRAND_FINALE': (0.30, 0.35),
    'MURDER': (0.30, 0.35),
    'CORROSIVE_WAVE': (0.30, 0.35),
    # Supporting Silent archetype terminals (-0.1 adjusted, SPEEDSTER excluded)
    'ENVENOM': (0.20, 0.25),
    'PHANTOM_BLADES': (0.20, 0.25),
    'FAN_OF_KNIVES': (0.20, 0.25),
    'TRACKING': (0.20, 0.25),
    'NIGHTMARE': (0.20, 0.25),
    'BURST': (0.15, 0.20),
    'FINISHER': (0.15, 0.20),
    'MEMENTO_MORI': (0.15, 0.20),
    'STRANGLE': (0.10, 0.15),
    'SHADOW_STEP': (0.10, 0.15),
    'INFINITE_BLADES': (0.10, 0.15),
    # Colorless / Event terminals
    'PANACHE': (0.20, 0.25),
    'GOLD_AXE': (0.20, 0.25),
    'MAUL': (0.20, 0.25),
    'HIDDEN_GEM': (0.10, 0.15),
}

CARD_DRAW_PRIORS = {
    'EXPERTISE': (0.60, 0.70),
    'SCRAWL': (0.50, 0.60),
    'CALCULATED_GAMBLE': (0.50, 0.60),
    'ACROBATICS': (0.45, 0.60),
    'MASTER_OF_STRATEGY': (0.45, 0.60),
    'ADRENALINE': (0.35, 0.35),
    'REFLEX': (0.35, 0.50),
    'BRIGHTEST_FLAME': (0.35, 0.50),
    'SOUL': (0.30, 0.45),
    'BACKFLIP': (0.30, 0.30),
    'TOOLS_OF_THE_TRADE': (0.30, 0.35),
    'IMPATIENCE': (0.25, 0.35),
    'RESTLESSNESS': (0.25, 0.35),
    'PREDATOR': (0.25, 0.25),
    'PREPARED': (0.15, 0.30),
    'SECRET_TECHNIQUE': (0.25, 0.30),
    'SECRET_WEAPON': (0.25, 0.30),
    'ANOINTED': (0.25, 0.30),
    'WISH': (0.25, 0.30),
    'THINKING_AHEAD': (0.20, 0.25),
    'SEEKER_STRIKE': (0.20, 0.25),
    'STRATAGEM': (0.20, 0.25),
    'NEOWS_FURY': (0.20, 0.25),
    'RELAX': (0.20, 0.25),
    'DAGGER_THROW': (0.15, 0.15),
    'ESCAPE_PLAN': (0.15, 0.15),
    'FINESSE': (0.15, 0.15),
    'FLASH_OF_STEEL': (0.15, 0.15),
}

CARD_ENERGY_PRIORS = {
    'TACTICIAN': (0.40, 0.60),
    'PRODUCTION': (0.40, 0.50),
    'ADRENALINE': (0.30, 0.50),
    'BRIGHTEST_FLAME': (0.35, 0.50),
    'LUMINESCE': (0.35, 0.50),
    'MASTER_PLANNER': (0.35, 0.45),
    'BULLET_TIME': (0.30, 0.40),
    'SIDESTEP': (0.25, 0.40),
    'OUTMANEUVER': (0.25, 0.40),
    'ENLIGHTENMENT': (0.25, 0.40),
    'AUTOMATION': (0.25, 0.35),
    'RESTLESSNESS': (0.25, 0.35),
    'POUNCE': (0.20, 0.25),
    'HAND_TRICK': (0.20, 0.25),
    'RELAX': (0.20, 0.25),
    'FUEL': (0.20, 0.20),
    'UP_MY_SLEEVE': (0.10, 0.15),
    'PINPOINT': (0.10, 0.15),
}

CARD_SCALING_PRIORS = {
    'APOTHEOSIS': (0.50, 0.55),
    'WRAITH_FORM': (0.40, 0.50),
    'FOOTWORK': (0.35, 0.45),
    'AFTERIMAGE': (0.35, 0.40),
    'WELL_LAID_PLANS': (0.30, 0.40),
    'ETERNAL_ARMOR': (0.30, 0.40),
    'PROWESS': (0.25, 0.35),
    'ABRASIVE': (0.25, 0.30),
    'PREP_TIME': (0.25, 0.35),
    'ROLLING_BOULDER': (0.25, 0.35),
    'FASTEN': (0.20, 0.30),
    'CALAMITY': (0.20, 0.25),
    'ANTICIPATE': (0.15, 0.20),
}

CARD_MITIGATION_PRIORS = {
    'APPARITION': (0.45, 0.55),
    'MALAISE': (0.40, 0.50),
    'PIERCING_WAIL': (0.35, 0.45),
    'DARK_SHACKLES': (0.30, 0.40),
    'LEG_SWEEP': (0.30, 0.35),
    'EQUILIBRIUM': (0.30, 0.35),
    'SUPPRESS': (0.30, 0.40),
    'PANIC_BUTTON': (0.30, 0.35),
    'SHADOWMELD': (0.25, 0.35),
    'SHOCKWAVE': (0.25, 0.35),
    'BLUR': (0.25, 0.30),
    'DASH': (0.25, 0.30),
    'ULTIMATE_DEFEND': (0.25, 0.30),
    'RELAX': (0.25, 0.30),
    'MIRAGE': (0.20, 0.25),
    'SURVIVOR': (0.15, 0.20),
    'NEUTRALIZE': (0.15, 0.20),
    'DEFEND_SILENT': (0.10, 0.15),
}

# Archetype-specific sources & payoffs (per-card)
CARD_SHIV_SOURCE = {
    'BLADE_DANCE': (0.60, 0.80),
    'CLOAK_AND_DAGGER': (0.25, 0.50),
    'LEADING_STRIKE': (0.40, 0.45),
    'INFINITE_BLADES': (0.50, 0.60),
    'BLADE_OF_INK': (0.45, 0.65),
    'HIDDEN_DAGGERS': (0.40, 0.55),
    'UP_MY_SLEEVE': (0.60, 0.80),
    'STORM_OF_STEEL': (0.60, 0.75),
    'FAN_OF_KNIVES': (0.80, 1.00),
    'SHIV': (0.25, 0.35),
}

CARD_SHIV_PAYOFF = {
    'ACCURACY': (1.00, 1.00),
    'PHANTOM_BLADES': (0.90, 1.00),
    'KNIFE_TRAP': (1.00, 1.00),
    'FAN_OF_KNIVES': (0.60, 0.70),
    'FINISHER': (0.70, 0.80),
    'SERPENT_FORM': (0.50, 0.60),
    'AFTERIMAGE': (0.50, 0.60),
    'ENVENOM': (0.50, 0.60),
    'STRANGLE': (0.50, 0.60),
    'PANACHE': (0.50, 0.60),
    'GOLD_AXE': (0.40, 0.50),
}

CARD_POISON_SOURCE = {
    'DEADLY_POISON': (0.50, 0.70),
    'POISONED_STAB': (0.35, 0.45),
    'SNAKEBITE': (0.60, 0.80),
    'BOUNCING_FLASK': (0.70, 0.90),
    'NOXIOUS_FUMES': (0.70, 0.90),
    'HAZE': (0.45, 0.65),
    'CORROSIVE_WAVE': (0.60, 0.80),
    'OUTBREAK': (0.80, 1.00),
    'ENVENOM': (0.50, 0.70),
    'BUBBLE_BUBBLE': (0.40, 0.55),
}

CARD_POISON_PAYOFF = {
    'ACCELERANT': (1.00, 1.00),
    'BUBBLE_BUBBLE': (1.00, 1.00),
    'MIRAGE': (1.00, 1.00),
    'OUTBREAK': (0.60, 0.70),
    'CORROSIVE_WAVE': (0.40, 0.50),
    'REND': (0.40, 0.50),
}

CARD_DISCARD_SOURCE = {
    'CALCULATED_GAMBLE': (0.90, 1.00),
    'STORM_OF_STEEL': (0.80, 0.85),
    'SHADOW_STEP': (0.70, 0.75),
    'TOOLS_OF_THE_TRADE': (0.60, 0.70),
    'PREPARED': (0.40, 0.70),
    'HIDDEN_DAGGERS': (0.50, 0.55),
    'ACROBATICS': (0.40, 0.45),
    'DAGGER_THROW': (0.35, 0.35),
    'SURVIVOR': (0.30, 0.30),
}

CARD_DISCARD_PAYOFF = {
    'REFLEX': (1.00, 1.00),
    'TACTICIAN': (1.00, 1.00),
    'MEMENTO_MORI': (1.00, 1.00),
    'ABRASIVE': (0.80, 0.85),
    'FLICK_FLACK': (0.70, 0.75),
    'RICOCHET': (0.70, 0.75),
    'UNTOUCHABLE': (0.70, 0.75),
    'HAZE': (0.70, 0.75),
    'HAND_TRICK': (0.60, 0.65),
    'MASTER_PLANNER': (0.70, 0.80),
}

RELIC_TERMINAL_PRIORS = {
    'SNECKO_SKULL': 0.25,
    'KUNAI': 0.25,
    'SHURIKEN': 0.25,
    'TOUGH_BANDAGES': 0.25,
    'TINGSHA': 0.20,
    'HELICAL_DART': 0.20,
    'UNSETTLING_LAMP': 0.20,
    'LOST_WISP': 0.15,
    'KUSARIGAMA': 0.15,
    'LETTER_OPENER': 0.15,
    'PEN_NIB': 0.15,
    'TWISTED_FUNNEL': 0.15,
}

RELIC_DRAW_PRIORS = {
    'RUNIC_PYRAMID': 0.50,
    'PAELS_BLOOD': 0.50,
    'RING_OF_THE_DRAKE': 0.45,
    'POCKETWATCH': 0.40,
    'UNCEASING_TOP': 0.35,
    'RING_OF_THE_SNAKE': 0.25,
    'BAG_OF_PREPARATION': 0.25,
    'GAMBLING_CHIP': 0.25,
    'CENTENNIAL_PUZZLE': 0.25,
    'IRON_CLUB': 0.25,
    'GAME_PIECE': 0.20,
    'PENDULUM': 0.20,
    'POLLINOUS_CORE': 0.20,
    'BOOMING_CONCH': 0.20,
    'RINGING_TRIANGLE': 0.20,
    'JOSS_PAPER': 0.15,
}

RELIC_ENERGY_PRIORS = {
    'ECTOPLASM': 0.60,
    'SOZU': 0.60,
    'PHILOSOPHERS_STONE': 0.60,
    'BLESSED_ANTLER': 0.60,
    'BLOOD_SOAKED_ROSE': 0.60,
    'VELVET_CHOKER': 0.60,
    'SPIKED_GAUNTLETS': 0.60,
    'WHISPERING_EARRING': 0.60,
    'PUMPKIN_CANDLE': 0.50,
    'BREAD': 0.50,
    'PAELS_FLESH': 0.40,
    'VERY_HOT_COCOA': 0.35,
    'MUMMIFIED_HAND': 0.35,
    'ICE_CREAM': 0.30,
    'HAPPY_FLOWER': 0.25,
    'LANTERN': 0.25,
    'NUNCHAKU': 0.25,
    'ART_OF_WAR': 0.25,
    'CANDELABRA': 0.25,
    'CHANDELIER': 0.25,
    'RADIANT_PEARL': 0.25,
    'PAELS_TEARS': 0.25,
    'BRILLIANT_SCARF': 0.25,
    'JEWELED_MASK': 0.25,
    'CROSSBOW': 0.25,
    'GREMLIN_HORN': 0.20,
    'VENERABLE_TEA_SET': 0.20,
    'BOOMING_CONCH': 0.20,
    'SEAL_OF_GOLD': 0.20,
    'VEXING_PUZZLEBOX': 0.20,
    'CHEMICAL_X': 0.20,
}

RELIC_SCALING_PRIORS = {
    'RAINBOW_RING': 0.30,
    'TOASTY_MITTENS': 0.30,
    'SWORD_OF_JADE': 0.30,
    'RAZOR_TOOTH': 0.30,
    'GIRYA': 0.25,
    'THROWING_AXE': 0.25,
    'MUSIC_BOX': 0.25,
    'ORNAMENTAL_FAN': 0.20,
    'DAUGHTER_OF_THE_WIND': 0.20,
    'HISTORY_COURSE': 0.20,
    'VAJRA': 0.15,
    'ODDLY_SMOOTH_STONE': 0.15,
    'BELT_BUCKLE': 0.15,
    'SPARKLING_ROUGE': 0.15,
    'SLING_OF_COURAGE': 0.15,
    'EMBER_TEA': 0.15,
    'AKABEKO': 0.15,
}

RELIC_MITIGATION_PRIORS = {
    'PAPER_KRANE': 0.35,
    'INTIMIDATING_HELMET': 0.20,
    'THE_ABACUS': 0.20,
    'ORNAMENTAL_FAN': 0.20,
    'DAUGHTER_OF_THE_WIND': 0.20,
    'TOUGH_BANDAGES': 0.25,
    'TUNING_FORK': 0.15,
}

RELIC_SHIV_SOURCE = {
    'NINJA_SCROLL': 0.50,
}

RELIC_SHIV_PAYOFF = {
    'HELICAL_DART': 1.00,
    'KUNAI': 0.70,
    'SHURIKEN': 0.70,
    'ORNAMENTAL_FAN': 0.60,
    'KUSARIGAMA': 0.60,
    'DAUGHTER_OF_THE_WIND': 0.50,
    'NUNCHAKU': 0.40,
    'PEN_NIB': 0.40,
}

RELIC_POISON_SOURCE = {
    'TWISTED_FUNNEL': 0.50,
    'SNECKO_SKULL': 0.50,
}

RELIC_POISON_PAYOFF = {
    'SNECKO_SKULL': 0.80,
    'UNSETTLING_LAMP': 0.60,
}

RELIC_DISCARD_SOURCE = {
    'GAMBLING_CHIP': 0.50,
}

RELIC_DISCARD_PAYOFF = {
    'TINGSHA': 1.00,
    'TOUGH_BANDAGES': 1.00,
}


def load_raw_cards(catalog_path=None) -> dict[str, dict]:
    path = Path(catalog_path or ROOT / 'catalogs/game-0.111.0.raw.json')
    raw = json.loads(path.read_text(encoding='utf-8'))
    return {c['id']: c for c in raw['cards']}


def card_prior_vector(card_id: str, card_meta: dict | None, upgraded: bool) -> np.ndarray:
    vec = np.zeros(PRIOR_DIM, dtype=np.float32)
    idx = 1 if upgraded else 0
    if card_meta is not None:
        ctype = card_meta.get('type', '')
        raw_cost = card_meta.get('cost', 0)
        if upgraded and card_id in UPGRADED_COST_OVERRIDES:
            raw_cost = UPGRADED_COST_OVERRIDES[card_id]
        if ctype in ('Status', 'Curse', 'Quest') or raw_cost < 0:
            vec[0] = 0.0
            vec[4] = 1.0  # clutter / unplayable
        else:
            vec[0] = float(raw_cost) / 3.0
        if ctype == 'Attack':
            vec[1] = 1.0
        elif ctype == 'Skill':
            vec[2] = 1.0
        elif ctype == 'Power':
            vec[3] = 1.0
        calls = '\n'.join(card_meta.get('calls', ()))
    else:
        calls = ''

    vec[5] = CARD_TERMINAL_PRIORS.get(card_id, (0.0, 0.0))[idx]
    vec[6] = CARD_DRAW_PRIORS.get(card_id, (0.0, 0.0))[idx]
    vec[7] = CARD_ENERGY_PRIORS.get(card_id, (0.0, 0.0))[idx]
    vec[8] = CARD_SCALING_PRIORS.get(card_id, (0.0, 0.0))[idx]
    if card_id in CARD_MITIGATION_PRIORS:
        vec[9] = CARD_MITIGATION_PRIORS[card_id][idx]
    elif 'GainBlock(' in calls or 'Apply<MegaCrit.Sts2.Core.Models.Powers.WeakPower>' in calls:
        vec[9] = 0.20 if upgraded else 0.15

    vec[10] = CARD_SHIV_SOURCE.get(card_id, (0.0, 0.0))[idx]
    vec[11] = CARD_SHIV_PAYOFF.get(card_id, (0.0, 0.0))[idx]
    vec[12] = CARD_POISON_SOURCE.get(card_id, (0.0, 0.0))[idx]
    vec[13] = CARD_POISON_PAYOFF.get(card_id, (0.0, 0.0))[idx]
    vec[14] = CARD_DISCARD_SOURCE.get(card_id, (0.0, 0.0))[idx]
    vec[15] = CARD_DISCARD_PAYOFF.get(card_id, (0.0, 0.0))[idx]
    return vec


def relic_prior_vector(relic_id: str) -> np.ndarray:
    vec = np.zeros(PRIOR_DIM, dtype=np.float32)
    vec[5] = RELIC_TERMINAL_PRIORS.get(relic_id, 0.0)
    vec[6] = RELIC_DRAW_PRIORS.get(relic_id, 0.0)
    vec[7] = RELIC_ENERGY_PRIORS.get(relic_id, 0.0)
    vec[8] = RELIC_SCALING_PRIORS.get(relic_id, 0.0)
    vec[9] = RELIC_MITIGATION_PRIORS.get(relic_id, 0.0)
    vec[10] = RELIC_SHIV_SOURCE.get(relic_id, 0.0)
    vec[11] = RELIC_SHIV_PAYOFF.get(relic_id, 0.0)
    vec[12] = RELIC_POISON_SOURCE.get(relic_id, 0.0)
    vec[13] = RELIC_POISON_PAYOFF.get(relic_id, 0.0)
    vec[14] = RELIC_DISCARD_SOURCE.get(relic_id, 0.0)
    vec[15] = RELIC_DISCARD_PAYOFF.get(relic_id, 0.0)
    return vec


def build_symbol_prior_tables(symbols: list[str], catalog_path=None) -> tuple[np.ndarray, np.ndarray, int]:
    """Return ``(table_u0[n_symbols, PRIOR_DIM], table_u1[n_symbols, PRIOR_DIM], upgrade1_symbol_index)``."""
    cards = load_raw_cards(catalog_path)
    n = len(symbols)
    table_u0 = np.zeros((n, PRIOR_DIM), dtype=np.float32)
    table_u1 = np.zeros((n, PRIOR_DIM), dtype=np.float32)
    upgrade1_idx = -1
    for i, sym in enumerate(symbols):
        if sym == 'upgrade:1':
            upgrade1_idx = i
        elif sym.startswith('card:'):
            cid = sym.split(':', 1)[1]
            meta = cards.get(cid)
            table_u0[i] = card_prior_vector(cid, meta, upgraded=False)
            table_u1[i] = card_prior_vector(cid, meta, upgraded=True)
        elif sym.startswith('relic:'):
            rid = sym.split(':', 1)[1]
            rvec = relic_prior_vector(rid)
            table_u0[i] = rvec
            table_u1[i] = rvec
    return table_u0, table_u1, upgrade1_idx


def compute_token_context(priors: torch.Tensor) -> torch.Tensor:
    """Compute 8-dim per-token deck-conditioned context vector from ``priors[B, T, 16]``.

    Every feature is attached to each individual card/relic token ``t`` so that
    each token directly carries how well the rest of the current build supports
    its cost, terminal role, or archetype synergy (Shiv / Poison / Discard).
    """
    cost = priors[:, :, 0:1]
    is_card = (priors[:, :, 1:5].sum(dim=-1, keepdim=True) > 0).float()
    terminal = priors[:, :, 5:6]
    draw = priors[:, :, 6:7]
    energy = priors[:, :, 7:8]
    scaling = priors[:, :, 8:9]
    mitigation = priors[:, :, 9:10]
    shiv_src = priors[:, :, 10:11]
    shiv_pay = priors[:, :, 11:12]
    poison_src = priors[:, :, 12:13]
    poison_pay = priors[:, :, 13:14]
    disc_src = priors[:, :, 14:15]
    disc_pay = priors[:, :, 15:16]

    deck_cards = is_card.sum(dim=1, keepdim=True).clamp(min=1.0)
    deck_scale = deck_cards / 12.0

    tot_cost = cost.sum(dim=1, keepdim=True)
    tot_draw = draw.sum(dim=1, keepdim=True)
    tot_energy = energy.sum(dim=1, keepdim=True)
    tot_def = (scaling + mitigation).sum(dim=1, keepdim=True)

    # Exclude self when checking whether OTHER cards/relics supply the synergy
    other_shiv_src = shiv_src.sum(dim=1, keepdim=True) - shiv_src
    other_shiv_pay = shiv_pay.sum(dim=1, keepdim=True) - shiv_pay
    other_poison_src = poison_src.sum(dim=1, keepdim=True) - poison_src
    other_poison_pay = poison_pay.sum(dim=1, keepdim=True) - poison_pay
    other_disc_src = disc_src.sum(dim=1, keepdim=True) - disc_src
    other_disc_pay = disc_pay.sum(dim=1, keepdim=True) - disc_pay

    energy_supply = 1.0 + 0.6 * tot_energy
    draw_density = tot_draw / deck_scale
    def_density = tot_def / deck_scale

    # 1. Per-card energy strain: card's own cost vs build's total energy supply
    c_energy_strain = cost / energy_supply
    # 2. Per-card deck-crowding strain: card's own cost * mean deck cost / energy supply
    c_crowding = cost * (tot_cost / deck_cards) / energy_supply
    # 3. Per-token terminal * deck draw density support
    c_term_draw = terminal * draw_density
    # 4. Per-token terminal * deck energy supply support
    c_term_energy = terminal * energy_supply / (1.0 + cost)
    # 5. Per-token terminal * deck defense/scaling survival support
    c_term_def = terminal * def_density
    # 6. Per-token Shiv synergy support (payoff card sees shiv sources; shiv source sees payoffs)
    c_shiv_syn = shiv_pay * other_shiv_src + shiv_src * other_shiv_pay
    # 7. Per-token Poison synergy support (payoff card sees poison sources; source sees payoffs)
    c_poison_syn = poison_pay * other_poison_src + poison_src * other_poison_pay
    # 8. Per-token Discard/Sly synergy support (Sly/payoff sees discard triggers; trigger sees Sly)
    c_disc_syn = disc_pay * other_disc_src + disc_src * other_disc_pay

    return torch.cat([
        c_energy_strain,
        c_crowding,
        c_term_draw,
        c_term_energy,
        c_term_def,
        c_shiv_syn,
        c_poison_syn,
        c_disc_syn,
    ], dim=-1)
