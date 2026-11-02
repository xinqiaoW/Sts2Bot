"""Current-deck event counterfactuals; no imagined future cards or hidden rolls."""
from copy import deepcopy
import math

from train.advisor_service import normalize_card
from train.reward_policy import score_weighting
from train.scoring_horizon import scoring_horizon, survival_budget
from .route_policy import next_floors
from .event_policy import event_card_addition, event_health_delta, event_value


class EventCombat:
    def __init__(self, policy, state, raw):
        self.policy, self.state = policy, state
        self.build = policy.model.project(raw)
        self.cache = {}
        config = policy.config
        self.horizon = scoring_horizon(policy.model.catalog, policy.model.scorer.predictor.trained_targets, state,
            elite_loss_threshold=config['elite_target_loss_threshold'],
            elite_safety_margin=config['elite_safety_margin'],
            boss_after_act_floor=config['boss_target_after_act_floor'],
            short_floors=lambda: next_floors(state, lambda r, n: policy.targets(state, r, n),
                                            config['unknown_combat_probability']),
            score_elites=lambda act, targets: dict(expected_hp_loss=self.loss(self.build, targets, act)))
        policy.model.warnings.extend(self.horizon['warnings'])
        self.act = self.horizon['encounter_act_id']
        self.future = self.horizon['next_floors']
        self.targets = self.horizon['long_targets']
        self.margin = config['elite_safety_margin'] if self.horizon['long_target_room'] == 'Elite' else config['boss_safety_margin']
        self.budget = None if not self.targets else survival_budget(state['hp'], self.future, self.targets,
            lambda targets: self.loss(self.build, targets, self.act), safety_margin=self.margin,
            sequential=self.horizon.get('long_target_aggregation') == 'max')
        short, _ = self.losses(self.build)
        self.weights = score_weighting(short, policy.reward_config, budget=self.budget)
        self.baseline = self.evaluate(self.build)

    def loss(self, build, targets, act):
        key = (build.id, act, tuple(sorted(targets.items())))
        if key not in self.cache:
            result = self.policy.model.scorer.score_many([dict(build=build.to_dict(), targets=targets,
                max_hp=self.state['maxHp'], encounter_act_id=act)], strict=False)[0]
            loss = result['expected_hp_loss']
            if not math.isfinite(loss) or loss < 0:
                raise ValueError('Invalid event combat loss')
            self.policy.model.warnings.extend(result.get('warnings', []))
            self.policy.model.warnings.extend('untrained_feature:' + k for k in result.get('untrained_features', []))
            self.cache[key] = loss
        return self.cache[key]

    def losses(self, build):
        short, count = 0., 0.
        for i, floor in enumerate(self.future):
            weight = floor.get('combat_probability', 1.) * self.policy.reward_config['short_floor_weights'][i]
            if weight:
                short += weight * self.loss(build, floor['targets'], self.act)
                count += weight
        long = (max(self.loss(build, {t: 1.}, self.act) for t in self.targets)
                if self.horizon.get('long_target_aggregation') == 'max'
                else self.loss(build, self.targets, self.act)) if self.targets else 0.
        return (short / count if count else None), long

    def evaluate(self, build):
        short, long = self.losses(build)
        return dict(short_expected_hp_loss=short, long_expected_hp_loss=long,
                    score=-(short or 0.) * self.weights['short_weight'] - long * self.weights['long_weight'])

    def safe_after(self, option):
        hp = self.state['hp'] + event_health_delta(option, self.state)
        return (not option.get('lethal') and hp > 0 and
                (self.budget is None or hp - self.state['hp'] + self.budget['remaining_hp'] > self.margin))


def adjust_event_cards(policy, state, options, context, raw, scores, reasons):
    event = context['eventId']
    additions = {o['index']: event_card_addition(event, o) for o in options}
    additions = {i: a for i, a in additions.items() if a is not None}
    bridge = event == 'SLIPPERY_BRIDGE' and any(o.get('id', '').split('.')[-1] == 'OVERCOME' for o in options)
    if not additions and not bridge:
        return set()
    combat = EventCombat(policy, state, raw)
    policy.last_report['event_combat'] = dict(horizon=combat.horizon, weighting=combat.weights,
                                            baseline=combat.baseline, evaluations={})
    details = policy.last_report['event_combat']['evaluations']
    rejected = set()
    for option in options:
        index = option['index']
        if index not in additions:
            continue
        addition = additions[index]
        # Replace the old generic card bonus with a complete-bundle estimate.
        without_card_prior = dict(policy.config, event_card_value=0.)
        scores[index] += (event_value(event, option, state, without_card_prior)[0]
                          - event_value(event, option, state, policy.config)[0])
        cards = addition['cards']
        supported = cards is not None and all(c['id'] in policy.model.catalog.cards and
            c['id'] not in policy.model.catalog.excluded['cards'] for c in cards)
        gain = None
        if supported:
            candidate = deepcopy(raw)
            candidate['cards'].extend(deepcopy(cards))
            after = combat.evaluate(policy.model.project(candidate))
            gain = after['score'] - combat.baseline['score']
            scores[index] += gain
        else:
            after = None
            # An omitted event card is not a zero-cost card. Explicit prior,
            # not a fabricated model score; safe alternatives take precedence.
            scores[index] -= policy.config['event_unknown_card_cost'] * addition['count']
            policy.model.warnings.append('event_card_addition_unmodeled:' + option['id'])
        reasons[index] = 'event_card_addition_model' if supported else 'event_card_addition_unknown_prior'
        details[index] = dict(addition=addition, after=after, combat_gain=gain)
        if combat.weights['mode'] == 'sufficient' and (gain is None or gain <= policy.config['event_card_min_gain']):
            alternatives = [o for o in options if o['index'] not in additions and combat.safe_after(o)]
            if alternatives:
                rejected.add(index)
                reasons[index] = 'sufficient_combat_avoid_forced_card_addition'
    if bridge:
        remove = next(o for o in options if o.get('id', '').split('.')[-1] == 'OVERCOME')
        index = remove['index']
        previews = [p for p in remove.get('cards', []) if p.get('deckIndex', -1) >= 0]
        after, damage = None, None
        if len(previews) == 1:
            preview = previews[0]
            deck_index = preview['deckIndex']
            if type(deck_index) is not int or not 0 <= deck_index < len(raw['cards']):
                raise ValueError('Bridge removal has invalid owned deck index')
            owned = raw['cards'][deck_index]
            if normalize_card(owned) != normalize_card(preview['card']):
                raise ValueError('Bridge removal preview differs from owned card')
            if owned['id'] in policy.model.catalog.cards and owned['id'] not in policy.model.catalog.excluded['cards']:
                candidate = deepcopy(raw)
                candidate['cards'].pop(deck_index)
                after = combat.evaluate(policy.model.project(candidate))
                damage = max((after['short_expected_hp_loss'] or 0.) - (combat.baseline['short_expected_hp_loss'] or 0.),
                             after['long_expected_hp_loss'] - combat.baseline['long_expected_hp_loss'])
                scores[index] = after['score'] - combat.baseline['score']
        critical = damage is None or damage >= policy.config['bridge_key_card_loss_threshold']
        all_holds = [o for o in options if o.get('id', '').split('.')[-1].startswith('HOLD_ON')]
        holds = [o for o in all_holds if combat.safe_after(o)]
        # Stop paying HP when the budget is exhausted, even if the model gives
        # deleting the card an even worse score. Otherwise a very valuable
        # card could cause repeated unsafe rerolls despite the protection gate.
        if not remove.get('lethal'):
            unsafe_holds = {o['index'] for o in all_holds} - {o['index'] for o in holds}
            rejected.update(unsafe_holds)
            reasons.update((i, 'bridge_reroll_exceeds_safe_hp_budget') for i in unsafe_holds)
        if critical and holds:
            rejected.add(index)
            reasons[index] = 'bridge_protect_key_card_with_safe_hp_budget'
        elif damage is None:
            # No safe reroll: a forced removal is legal, but never labelled a
            # model-approved deletion of an unrepresented card.
            scores[index] = -policy.config['event_unknown_card_cost']
            reasons[index] = 'bridge_unknown_card_no_safe_reroll'
        else:
            reasons[index] = 'bridge_current_deck_short_and_long_removal'
        details[index] = dict(after=after, worst_loss_increase=damage, critical=critical,
                              safe_hold_options=[o['index'] for o in holds])
    # Resource rules and card adjustments may never undo a visible lethal flag.
    for option in options:
        if option.get('lethal'):
            scores[option['index']] = -1e9
            reasons[option['index']] = 'visible_lethal_option'
    policy.last_report['event_rejected_options'] = sorted(rejected)
    return rejected
