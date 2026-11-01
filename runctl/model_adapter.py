"""Explicit projection from real owned state to the trained model's domain.

Projection never changes the game. Every excluded relic/card is reported to the
decision log; unsupported acquisition state is not silently fabricated.
"""
from copy import copy, deepcopy

from damage_model.schema import Build
from train.advisor_service import normalize_card, normalize_relic


class ModelAdapter:
    def __init__(self, scorer):
        self.scorer = scorer
        self.catalog = copy(scorer.catalog)
        self.catalog.config = dict(scorer.catalog.config)
        self.catalog.normalized_relic_ids = set(scorer.catalog.normalized_relic_ids)
        self.catalog.normalized_relic_ids.update(self.catalog.excluded['relics'])
        scorer.catalog = self.catalog
        self.warnings = []

    def project(self, raw):
        value = deepcopy(raw)
        value['ancient_history'] = list(value['ancient_history'])
        # Native AncientChoiceHistoryEntry stores the penultimate title-key
        # segment. Sea Glass titles are SEA_GLASS.<character>.title, so its
        # recorded TextKey is a character ID instead of the relic ID. Resolve
        # only this known public alias, with the actual owned relic as evidence.
        for index, (act, ancient, reward) in enumerate(value['ancient_history']):
            if (ancient == 'OROBAS' and reward in {'IRONCLAD', 'SILENT', 'REGENT', 'NECROBINDER', 'DEFECT'}
                    and any(r['id'] == 'SEA_GLASS' for r in value['relics'])):
                value['ancient_history'][index] = [act, ancient, 'SEA_GLASS']
                self.warnings.append(f'ancient_history_alias:{reward}:SEA_GLASS')
        cards = []
        for card in value['cards']:
            cid = card['id']
            if cid not in self.catalog.cards or cid in self.catalog.excluded['cards']:
                self.warnings.append(f'excluded_card:{cid}')
                continue
            # Invalid state is not an excluded card: preserve the error rather
            # than pretending an unknown enchantment or counter has no effect.
            cards.append(normalize_card(card))
        if not cards:
            raise ValueError('No supported cards remain for model scoring')
        relics = []
        for relic in value['relics']:
            rid = relic['id']
            if rid not in self.catalog.relic_pool:
                self.warnings.append(f'excluded_relic:{rid}')
                continue
            try:
                relics.append(normalize_relic(relic))
            except ValueError as exc:
                # The user explicitly permits removing model-rejected relics
                # from scoring inputs, not from the actual run inventory.
                self.catalog.normalized_relic_ids.add(rid)
                self.warnings.append(f'excluded_relic:{rid}:{exc}')
        value['cards'], value['relics'] = cards, relics
        value.setdefault('family', 'autobot')
        # The set model accepts variable-length decks. Flag extrapolation when
        # a real run exceeds collection limits instead of dropping real cards.
        if len(cards) + 5 > self.catalog.config['max_deck_size']:
            self.catalog.config['max_deck_size'] = len(cards) + 5
            self.warnings.append('deck_size_extrapolation')
        colorless = sum(self.catalog.cards[c['id']]['pool'] == 'COLORLESS_CARD_POOL' for c in cards)
        if colorless > self.catalog.config['max_colorless']:
            self.catalog.config['max_colorless'] = colorless
            self.warnings.append('colorless_count_extrapolation')
        build = Build.from_dict(value)
        self.catalog.validate(build)
        return build

    def targets(self, act_id, room, visible_boss, *, weak=None):
        if room == 'Boss':
            ids = [visible_boss]
        else:
            ids = [e['id'] for e in self.catalog.acts[act_id]['encounters'] if e['room_type'] == room
                   and (weak is None or room != 'Monster' or e['weak'] == weak)]
        covered = [tid for tid in ids if f'{act_id}:{tid}' in self.scorer.predictor.trained_targets]
        if set(ids) != set(covered):
            self.warnings.append(f'uncovered_encounters:{act_id}:{sorted(set(ids)-set(covered))}')
        if not covered:
            raise ValueError(f'No trained {room} encounter for {act_id}')
        return dict.fromkeys(covered, 1 / len(covered))

    def score(self, builds, targets, max_hp):
        results = self.scorer.score_many([dict(build=b.to_dict(), targets=targets, max_hp=max_hp) for b in builds], strict=False)
        for result in results:
            self.warnings.extend(result.get('warnings', []))
            self.warnings.extend('untrained_feature:' + key for key in result['untrained_features'])
        return results
