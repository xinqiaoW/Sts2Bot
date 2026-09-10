from __future__ import annotations

import json
from pathlib import Path
import re
from .schema import Build


# Explicit initial support. Unknown persistent state is reported instead of fabricated.
# Ranges checked against game 0.111.0 IL; see docs/counter-state.md.
COUNTER_DOMAINS = {
    "HAPPY_FLOWER": {"TurnsSeen": [0, 1, 2]},
    "PEN_NIB": {"AttacksPlayed": list(range(10))},
    "NUNCHAKU": {"AttacksPlayed": list(range(10))},
    "TUNING_FORK": {"SkillsPlayed": list(range(10))},
    "GIRYA": {"TimesLifted": [0, 1, 2, 3]},
    "VENERABLE_TEA_SET": {"GainEnergyInNextCombat": [False, True]},
    "WINGED_BOOTS": {"TimesUsed": [0, 1, 2, 3]},
    "LAVA_ROCK": {"HasTriggered": [False, True]},
    "LAVA_LAMP": {"TookDamageThisCombat": [False]},
    "MAW_BANK": {"HasItemBeenBought": [False, True]},
}

# Ordinary scalar state checked against the same native 0.111.0 assembly.
# These are legal representative states for independent battles, not estimates
# of how often those states occur in human runs.
IMPORTED_COUNTER_DOMAINS = {
    'SILVER_CRUCIBLE': {'TimesUsed': list(range(4)), 'TreasureRoomsEntered': [0, 1, 2]},
    'FISHING_ROD': {'CombatsSeen': [0, 1, 2]},
    'PENDULUM': {'TurnsSeen': [0, 1, 2]},
    'SWORD_OF_STONE': {'ElitesDefeated': list(range(5))},
    'SILKEN_TRESS': {'IsUsed': [False, True]},
    'BOOK_OF_FIVE_RINGS': {'CardsAdded': list(range(5))},
    'BONE_TEA': {'CombatsLeft': [0, 1]},
    'EMBER_TEA': {'CombatsLeft': list(range(6))},
    'FAKE_HAPPY_FLOWER': {'TurnsSeen': list(range(5))},
    'FAKE_VENERABLE_TEA_SET': {'GainEnergyInNextCombat': [False, True]},
    'IRON_CLUB': {'CardsPlayed': list(range(4))},
    'JOSS_PAPER': {'CardsExhausted': list(range(5))},
    'LASTING_CANDY': {'CombatRewardsSeen': [0, 1, 2]},
    'PAELS_WING': {'RewardsSacrificed': [0, 1]},
    'POLLINOUS_CORE': {'TurnsSeen': list(range(4))},
    'PUMPKIN_CANDLE': {'KindleCount': list(range(6))},
    'TEA_OF_DISCOURTESY': {'CombatsLeft': [0, 1]},
    'WONGOS_MYSTERY_TICKET': {'CombatsFinished': list(range(6)), 'GaveRelic': [False, True]},
}
COUNTER_DOMAINS.update(IMPORTED_COUNTER_DOMAINS)


def validate_counter_relation(relic_id, state):
    if relic_id == 'WONGOS_MYSTERY_TICKET' and state['GaveRelic'] != (state['CombatsFinished'] >= 5):
        raise ValueError('Inconsistent mystery ticket counters')

# Their only acquisition action changes the deck or grants rewards already
# recorded in .run. The native fixture must not execute it a second time.
IMPORTED_ACQUISITION_RELICS = {
    'POMANDER', 'WHETSTONE', 'WAR_PAINT', 'EMPTY_CAGE', 'PRECISE_SCISSORS',
    'ASTROLABE', 'PANDORAS_BOX', 'CALLING_BELL',
    'GOLDEN_PEARL', 'LEAD_PAPERWEIGHT',
    'LARGE_CAPSULE', 'SCROLL_BOXES', 'HEFTY_TABLET', 'CURSED_PEARL', 'POTION_BELT',
    'SILKEN_TRESS', 'PUMPKIN_CANDLE',
    'JEWELRY_BOX', 'NEOWS_TORMENT', 'ARCHAIC_TOOTH',
    'ARCANE_SCROLL', 'BEAUTIFUL_BRACELET', 'BELT_BUCKLE', 'BIIIG_HUG',
    'BLOOD_SOAKED_ROSE', 'CAULDRON', 'CLAWS', 'DISTINGUISHED_CAPE',
    'DOLLYS_MIRROR', 'DOWSING_ROD', 'ELECTRIC_SHRYMP', 'FAKE_LEES_WAFFLE',
    'FRAGRANT_MUSHROOM', 'GLASS_EYE', 'GNARLED_HAMMER', 'KIFUDA',
    'LOST_COFFER', 'NEOWS_BONES', 'NEOWS_TALISMAN', 'NEW_LEAF',
    'NUTRITIOUS_SOUP', 'OLD_COIN', 'ORRERY', 'PAELS_CLAW', 'PAELS_GROWTH',
    'PAELS_HORN', 'PRECARIOUS_SHEARS', 'PRESERVED_FOG', 'PUNCH_DAGGER',
    'ROYAL_STAMP', 'SAND_CASTLE', 'SIGNET_RING', 'SMALL_CAPSULE',
    'STORYBOOK', 'TANXS_WHISTLE', 'TRI_BOOMERANG', 'YUMMY_COOKIE', 'DUSTY_TOME',
    'BYRDPIP', 'PAELS_LEGION',
}

# Saved card references only feed pickup/tooltips; those deck changes are in
# .run. Pet skins have valid native defaults and do not affect combat behavior.
# Pets are still summoned by BeforeCombatStart, independently of AfterObtained.
IMPORTED_DISPLAY_STATE_RELICS = {'ARCHAIC_TOOTH', 'DUSTY_TOME', 'BYRDPIP', 'PAELS_LEGION'}


class Catalog:
    def __init__(self, raw: dict, config: dict):
        self.raw, self.config = raw, config
        self.cards = {c["id"]: c for c in raw["cards"]}
        self.relics = {r["id"]: r for r in raw["relics"]}
        self.acts = {a["id"]: a for a in raw["acts"]}
        self.ancients = {a["id"]: a for a in raw["ancients"]}
        # Missing in historical catalogs; never infer eligibility from relic IDs.
        self.shared_ancients = set(raw.get('shared_ancients', []))
        if not self.shared_ancients <= self.ancients.keys():
            raise ValueError('Unknown shared ancient identifier')
        self.max_hp_relic_ids = {r['id'] for r in raw['relics'] if
            re.search(r"::(?:GainMaxHp|LoseMaxHp|SetMaxHp)\(", '\n'.join(r['calls']))
            or 'ModifyMaxHp' in r['declared_methods']}
        self.enchantments = {e['id']: e for e in raw.get('enchantments', [])
                             if e['id'] not in ('MOCK_FREE_ENCHANTMENT', 'DEPRECATED_ENCHANTMENT')}
        self.excluded = {"cards": {}, "relics": {}}
        self.card_pool = []
        imported = config.get('build_source') == 'spire_codex_run_v1'
        self.remove_max_hp_relics = imported and config.get('max_hp_relic_policy') == 'remove'
        self.explicitly_removed_relics = set(config.get('removed_relic_ids', [])) if imported else set()
        if not self.explicitly_removed_relics <= self.relics.keys():
            raise ValueError('Unknown removed relic identifier')
        self.normalized_relic_ids = self.explicitly_removed_relics | (
            self.max_hp_relic_ids if self.remove_max_hp_relics else set())
        for c in raw["cards"]:
            reason = None
            if c["pool"] not in ("SILENT_CARD_POOL", "COLORLESS_CARD_POOL", *(['CURSE_CARD_POOL', 'EVENT_CARD_POOL'] if imported else [])):
                reason = "other_character_or_special_pool"
            elif c["multiplayer_constraint"] == "MultiplayerOnly": reason = "multiplayer_only"
            elif c["rarity"] not in ("Common", "Uncommon", "Rare", "Basic", *(['Curse', 'Event', 'Ancient'] if imported else [])): reason = "requires_special_acquisition"
            elif any("PotionFactory::" in s or "PotionCmd::" in s for s in c["calls"]): reason = "potions_out_of_scope"
            if reason: self.excluded["cards"][c["id"]] = reason
            elif c["rarity"] != "Basic": self.card_pool.append(c["id"])
        self.relic_pool = []
        for r in raw["relics"]:
            calls = "\n".join(r["calls"])
            methods = r["declared_methods"]
            reason = None
            if r["id"] in config["excluded_relic_ids"]: reason = "user_excluded_or_cross_character"
            elif r['id'] in self.explicitly_removed_relics: reason = 'user_removed_from_input'
            elif r['id'] in self.max_hp_relic_ids:
                reason = "changes_max_hp"
            elif any("ShouldDie" in m or "DeathPrevent" in m for m in methods): reason = "resurrection_or_death_prevention"
            elif r["pool"] not in ("SILENT_RELIC_POOL", "SHARED_RELIC_POOL", "EVENT_RELIC_POOL"):
                reason = "other_character_pool"
            elif any("PotionFactory::" in s or "PotionCmd::" in s for s in r["calls"]): reason = "potions_out_of_scope"
            elif r["state_properties"] and not (imported and r['id'] in IMPORTED_DISPLAY_STATE_RELICS) and (r["id"] not in COUNTER_DOMAINS or (r['id'] in {*IMPORTED_COUNTER_DOMAINS, 'TUNING_FORK'} and not imported)):
                reason = "persistent_state_adapter_pending"
            elif "AfterObtained" in methods and not (imported and r['id'] in IMPORTED_ACQUISITION_RELICS):
                reason = "acquisition_effect_adapter_pending"
            if reason: self.excluded["relics"][r["id"]] = reason
            else: self.relic_pool.append(r["id"])

    @classmethod
    def load(cls, raw_path, config_path):
        return cls(json.loads(Path(raw_path).read_text(encoding="utf-8")),
                   json.loads(Path(config_path).read_text(encoding="utf-8")))

    def colorless_count(self, cards):
        return sum(self.cards[c.id]["pool"] == "COLORLESS_CARD_POOL" for c in cards)

    def targets(self, build):
        return sorted(self.acts[build.act_id]["encounters"],
                      key=lambda t:(not t['weak'],{'Monster':0,'Elite':1,'Boss':2}.get(t['room_type'],3),t['id']))

    def validate(self, build: Build):
        if build.act_id not in self.acts or self.acts[build.act_id]["act"] != build.act:
            raise ValueError("Act mismatch")
        if not 1 <= len(build.cards) <= self.config["max_deck_size"]:
            raise ValueError("Deck size outside range")
        for card in build.cards:
            if card.id not in self.cards or card.id in self.excluded["cards"]:
                raise ValueError(f"Disallowed card: {card.id}")
            if type(card.upgrade) is not int or not 0 <= card.upgrade <= self.cards[card.id]["max_upgrade_level"]:
                raise ValueError("Invalid card upgrade")
            if type(card.enchantment_id) is not str or type(card.enchantment_amount) is not int:
                raise ValueError('Invalid card enchantment fields')
            if card.enchantment_id:
                if card.enchantment_id not in self.enchantments or not 1 <= card.enchantment_amount <= 2147483647:
                    raise ValueError('Unknown enchantment or invalid amount')
            elif card.enchantment_amount != 0:
                raise ValueError('Enchantment amount without an enchantment')
        if self.colorless_count(build.cards) > self.config["max_colorless"]:
            raise ValueError("Too many colorless cards")
        ids = [r.id for r in build.relics]
        if len(ids) != len(set(ids)): raise ValueError("Duplicate relic")
        for relic in build.relics:
            if relic.id not in self.relic_pool: raise ValueError(f"Disallowed relic: {relic.id}")
            expected = COUNTER_DOMAINS.get(relic.id, {})
            state = dict(relic.state)
            if set(expected) != set(state): raise ValueError("Incomplete relic state")
            for key, value in state.items():
                if not any(type(value) is type(v) and value == v for v in expected[key]):
                    raise ValueError("Invalid counter value")
            validate_counter_relation(relic.id, state)
        self.validate_ancient_history(build.act, build.ancient_history, ids,
                                      allow_removed=bool(self.normalized_relic_ids))

    def validate_ancient_history(self, act, history, ids, allow_removed=False):
        if [h[0] for h in history] != list(range(1, act + 1)):
            raise ValueError("Ancient history must cover exactly the current and preceding acts")
        ancient_ids = []
        seen_shared = set()
        for source_act, ancient, relic in history:
            allowed = set(a for spec in self.acts.values() if spec["act"] == source_act for a in spec["ancients"])
            if source_act > 1:
                allowed |= self.shared_ancients
            if ancient in self.shared_ancients:
                if ancient in seen_shared:
                    raise ValueError('Shared ancient may appear only once per run')
                seen_shared.add(ancient)
            removed = allow_removed and relic in self.normalized_relic_ids
            if ancient not in allowed or relic not in self.ancients[ancient]["possible_relics"] or (relic not in ids and not removed):
                raise ValueError("Illegal ancient provenance")
            ancient_ids.append(relic)
        if any(r not in self.relics for r in ids):
            raise ValueError('Unknown relic in source inventory')
        extras = [r for r in ids if self.relics[r]['rarity'] == 'Ancient' and r not in ancient_ids]
        if extras:
            # Neow's Bones grants exactly two distinct Neow rewards. The source
            # importer validates the real gains and final inventory; later
            # removals may leave fewer than two. Never admit later-act rewards.
            bones = (1, 'NEOW', 'NEOWS_BONES') in history and 'NEOWS_BONES' in ids
            allowed = set(self.ancients['NEOW']['possible_relics']) - {'NEOWS_BONES'}
            if not bones or len(extras) > 2 or not set(extras) <= allowed:
                raise ValueError("Ancient relic without acquisition history")
