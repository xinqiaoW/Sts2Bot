"""Model input encoding, usable without installing the training framework."""
import numpy as np
from .catalog import COUNTER_DOMAINS
from .card_state import DEFAULTS, state_variants
from .schema import canonical


class Encoder:
    def __init__(self, specification):
        self.spec = specification
        self.positions = {key: i for i, key in enumerate(specification['features'])}

    @classmethod
    def from_catalog(cls, catalog):
        features = ['deck_size', 'max_hp', 'act']
        for card_id in sorted(set(catalog.card_pool) | set(catalog.raw['character']['starting_deck'])):
            features += [f'card:{card_id}:count', f'card:{card_id}:upgrades']
            for upgrade in range(catalog.cards[card_id]['max_upgrade_level'] + 1):
                for enchantment in sorted(catalog.enchantments):
                    prefix = f'enchanted:{card_id}:{upgrade}:{enchantment}'
                    features += [prefix + ':count', prefix + ':amount', prefix + ':amount_squared']
            if card_id in DEFAULTS:
                for state in state_variants(card_id):
                    for upgrade in range(catalog.cards[card_id]['max_upgrade_level'] + 1):
                        prefix = f'saved:{card_id}:{upgrade}:{canonical(dict(state))}'
                        features.append(prefix + ':count')
                        for enchantment in sorted(catalog.enchantments):
                            features += [prefix + ':' + enchantment + suffix for suffix in (':count', ':amount', ':amount_squared')]
        for relic_id in sorted(catalog.relic_pool):
            features += [f'relic:{relic_id}:present', f'relic:{relic_id}:order']
            features += [f'relic:{relic_id}:{key}' for key in sorted(COUNTER_DOMAINS.get(relic_id, {}))]
        features += ['target:' + a['id'] + ':' + t['id'] for a in catalog.raw['acts'] for t in a['encounters']]
        return cls({'features': list(dict.fromkeys(features)), 'game_sha256': catalog.raw['game_sha256'],
                    'card_state_encoding': 'card_upgrade_enchantment_saved_variants_v3'})

    def encode(self, build, target_id, max_hp):
        vector = np.zeros(len(self.positions), dtype=np.float32)

        def add(key, value):
            if key not in self.positions:
                raise ValueError(f'Unknown model feature: {key}')
            vector[self.positions[key]] += value

        add('deck_size', len(build.cards) / 45)
        add('max_hp', max_hp / 100)
        add('act', build.act / 3)
        for card in build.cards:
            add(f'card:{card.id}:count', 1 / 5)
            add(f'card:{card.id}:upgrades', card.upgrade / 5)
            if card.id in DEFAULTS:
                prefix = f'saved:{card.id}:{card.upgrade}:{canonical(dict(card.persistent_state))}'
                add(prefix + ':count', 1 / 5)
                if card.enchantment_id:
                    add(prefix + ':' + card.enchantment_id + ':count', 1 / 5)
                    add(prefix + ':' + card.enchantment_id + ':amount', card.enchantment_amount / 10)
                    add(prefix + ':' + card.enchantment_id + ':amount_squared', (card.enchantment_amount / 10) ** 2)
            if card.enchantment_id:
                prefix = f'enchanted:{card.id}:{card.upgrade}:{card.enchantment_id}'
                add(prefix + ':count', 1 / 5)
                add(prefix + ':amount', card.enchantment_amount / 10)
                add(prefix + ':amount_squared', (card.enchantment_amount / 10) ** 2)
        for index, relic in enumerate(build.relics):
            add(f'relic:{relic.id}:present', 1)
            add(f'relic:{relic.id}:order', (index + 1) / max(1, len(build.relics)))
            for key, value in relic.state:
                add(f'relic:{relic.id}:{key}', float(value) / 10)
        add('target:' + build.act_id + ':' + target_id, 1)
        return vector
