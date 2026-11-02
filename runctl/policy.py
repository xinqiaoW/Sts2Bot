"""Model-assisted whole-run policy. Only native public decision snapshots enter."""
from copy import deepcopy
import hashlib
import time

from train.reward_policy import RewardSelector, load_config
from train.score import BuildScorer
from train.scoring_horizon import scoring_horizon
from train.advisor_service import normalize_card
from .event_policy import event_value, doll_room_options
from .event_combat import adjust_event_cards
from .model_adapter import ModelAdapter
from .policy_config import load_policy_config, potion_priority, potion_reward_eligible
from .route_policy import plan_route, next_floors


class BotPolicy:
    def __init__(self, scorer=None, config=None):
        self.config = load_policy_config(**(config or {}))
        self.model = ModelAdapter(scorer or BuildScorer())
        self.reward_config = load_config(None, short_weight=self.config['short_weight'],
                                        long_weight=self.config['long_weight'], strict_features=False,
                                        **{k: self.config[k] for k in
                                           ('short_strength_loss_threshold', 'elite_safety_margin', 'boss_safety_margin',
                                            'weak_short_weight', 'weak_long_weight', 'post_boss_rollout_depth',
                                            'elite_target_loss_threshold', 'boss_target_after_act_floor',
                                            'samples_per_parent', 'keep_per_parent', 'lookahead_pairs',
                                            'leaf_top_fraction', 'leaf_bottom_fraction',
                                            'leaf_top_weight', 'leaf_bottom_weight', 'leaf_rank_power')})
        self.run_id = None
        self.pending_ancient = None
        self.last_report = {}

    def raw_build(self, state):
        raw = deepcopy(state['build'])
        if self.pending_ancient is not None:
            act, event, relic = self.pending_ancient
            if act == state['act'] and len(raw['ancient_history']) == act-1:
                raw['ancient_history'].append([act, event, relic['id']])
                if not any(r['id'] == relic['id'] for r in raw['relics']): raw['relics'].append(deepcopy(relic))
        return raw

    def choose(self, observation):
        started = time.monotonic()
        if observation['runId'] != self.run_id:
            self.run_id, self.pending_ancient = observation['runId'], None
        self.model.warnings = []
        state, options, screen = observation['state'], observation['options'], observation['screen']
        context = observation.get('context') or {}
        if [o['index'] for o in options] != list(range(len(options))): raise ValueError('Invalid option indices')
        self.last_report = dict(screen=screen, decisionSeq=observation['decisionSeq'], config=self.config)
        free_relics = [o for o in options if o.get('kind') == 'relic']
        if screen == 'EVENT' and context.get('eventId') == 'DOLL_ROOM':
            # Apply the explicit ban before the single-option shortcut.
            choice = self.event(state, options, context)
        elif screen == 'REWARDS' and all(o['kind'] in ('potion', 'potion_replace', 'leave', 'skip') for o in options):
            # Free potion decisions do not need a card model or the forced-choice shortcut.
            choices = [o for o in options if o['kind'] in ('potion', 'potion_replace')
                       and potion_reward_eligible(o, state['potions'], self.config)]
            if choices:
                selected = max(choices, key=lambda o: (potion_priority(o['id'], self.config), -o['index']))
            else:
                selected = next((o for o in options if o['kind'] in ('leave', 'skip')), None)
                if selected is None:
                    raise ValueError('No eligible potion reward or legal leave option')
            choice = selected['index']
            self.last_report.update(reason='potion_priority', potion_choice=selected)
        elif len(options) == 1:
            choice = 0
            self.last_report['reason'] = 'only_legal_option'
        elif free_relics and (screen in ('REWARDS', 'TREASURE') or screen == 'RELIC' and len(free_relics) == 1):
            # Ordinary rewards/chest contents are independent free pickups.
            # Only mutually exclusive relic offers, events and purchases need
            # comparison. Model limitations must not discard real free relics.
            choice = free_relics[0]['index']
            self.last_report['reason'] = 'take_free_relic'
        elif screen == 'CRYSTAL':
            # Reproducible policy randomness; unrelated to the game's seed/RNG.
            seed = f"{self.config['seed']}:{observation['decisionSeq']}"
            choice = int(hashlib.sha256(seed.encode()).hexdigest(), 16) % len(options)
            self.last_report['reason'] = 'uniform_hidden_cell'
        elif screen == 'EVENT':
            choice = self.event(state, options, context)
        else:
            raw = self.raw_build(state)
            build = self.model.project(raw)
            if screen == 'MAP':
                losses = {room: self.model.score([build], self.targets(state, room, normal_count=99), state['maxHp'])[0]['expected_hp_loss']
                          for room in ('Monster', 'Elite', 'Boss')}
                if 'normalCombatsCompleted' in state and state['normalCombatsCompleted'] < (3 if state['act'] == 1 else 2):
                    losses['MonsterWeak'] = self.model.score([build], self.targets(state, 'Monster', normal_count=0), state['maxHp'])[0]['expected_hp_loss']
                choice, plans = plan_route(state, options, losses, self.config)
                self.last_report.update(route_plans=plans, encounter_losses=losses)
            elif screen in ('CARD_REWARD', 'CHOOSE_CARD') or (screen == 'CARD_GRID' and context.get('action') in ('take', 'upgrade', 'remove')):
                choice = self.cards(state, options, raw, build,
                    fixed_depth=self.config['reward_rollout_depth']
                        if screen == 'CARD_REWARD' and context.get('postCombat') is True else None)
            elif screen == 'REST':
                normal_loss = self.model.score([build], self.targets(state), state['maxHp'])[0]['expected_hp_loss']
                urgent = state['hp'] < max(self.config['rest_hp_fraction']*state['maxHp'], normal_loss*1.5)
                priorities = {'HEAL': 100 if urgent else 2, 'SMITH': 20, 'LIFT': 16, 'DIG': 14, 'TOKE': 18}
                choice = max(options, key=lambda o: (priorities.get(o['id'].upper(), 5), -o['index']))['index']
                self.last_report.update(reason='rest_hp_and_combat_risk', urgent=urgent)
            else:
                choice = self.immediate(state, options, raw, build, screen, context)
        selected = options[choice]
        if screen == 'EVENT' and selected.get('relic') and context.get('eventId') in self.model.catalog.ancients:
            self.pending_ancient = (state['act'], context['eventId'], deepcopy(selected['relic']))
        self.last_report.update(choice=choice, warnings=sorted(set(self.model.warnings)), elapsed_seconds=time.monotonic()-started)
        return choice

    def targets(self, state, room='Monster', normal_count=None):
        count = state.get('normalCombatsCompleted') if normal_count is None else normal_count
        weak = None if count is None else count < (3 if state['act'] == 1 else 2)
        return self.model.targets(state['actId'], room, state['visibleBoss'], weak=weak)

    def search_card_builds(self, state, build, explicit, *, fixed_depth=None):
        # An empty offer list evaluates only the current build's skip branch.
        # Shops still need the same rollout risk definition after cards sell out.
        normal = RewardSelector(self.model.scorer, self.reward_config)
        horizon = scoring_horizon(self.model.catalog, self.model.scorer.predictor.trained_targets, state,
            elite_loss_threshold=self.config['elite_target_loss_threshold'],
            elite_safety_margin=self.config['elite_safety_margin'],
            short_floors=lambda: next_floors(state, lambda r, n: self.targets(state, r, n), self.config['unknown_combat_probability']),
            boss_after_act_floor=self.config['boss_target_after_act_floor'],
            score_elites=lambda act_id, targets: self.model.scorer.score_many([
                dict(build=build.to_dict(), max_hp=state['maxHp'], targets=targets, encounter_act_id=act_id)], strict=False)[0])
        future = horizon['next_floors']
        remaining = max(0, state['floorsToBoss']-1)
        depth = fixed_depth if fixed_depth is not None else min(
            normal.depth_for(state['floorsToBoss']), self.config['max_rollout_depth'], remaining)
        if horizon['projects_next_act'] and fixed_depth is None:
            depth = self.reward_config['post_boss_rollout_depth']
        request = dict(build=build.to_dict(), max_hp=state['maxHp'], budget_hp=state['hp'], options=explicit,
            floors_to_boss=state['floorsToBoss'], rollout_depth=depth,
            next_floors=future, long_targets=horizon['long_targets'], long_target_room=horizon['long_target_room'],
            long_target_aggregation=horizon.get('long_target_aggregation', 'mean'),
            encounter_act_id=horizon['encounter_act_id'], terminal=horizon['mode'] == 'terminal')
        result = normal.select(request)
        projected_loss = min(c['long_expected_hp_loss'] for c in result['candidates'])
        crisis = projected_loss > self.config['crisis_boss_loss_threshold']
        if crisis and (fixed_depth is not None or remaining > 0):
            expanded = dict(self.reward_config, samples_per_parent=self.config['crisis_samples_per_parent'],
                            keep_per_parent=self.config['crisis_keep_per_parent'])
            request['rollout_depth'] = depth+self.config['crisis_extra_depth'] if fixed_depth is not None else min(
                depth+self.config['crisis_extra_depth'], self.config['max_rollout_depth'], remaining)
            result = RewardSelector(self.model.scorer, expanded).select(request)
        self.model.warnings.extend(result['warnings'])
        self.model.warnings.extend('untrained_feature:' + k for k in result['untrained_features'])
        self.model.warnings.extend(horizon['warnings'])
        self.last_report.update(crisis=crisis, projected_long_loss=projected_loss,
            projected_boss_loss=projected_loss if horizon['long_target_room'] == 'Boss' else None,
            scoring_horizon=horizon,
            rollout_depth_mode='terminal' if horizon['mode'] == 'terminal' else 'fixed_reward' if fixed_depth is not None
                else 'post_boss' if horizon['projects_next_act'] else 'distance_to_boss',
            rollout_depth=result['rollout_depth'], samples_per_parent=result['config']['samples_per_parent'],
            keep_per_parent=result['config']['keep_per_parent'],
            lookahead_pairs=result['config']['lookahead_pairs'], stats=result['stats'],
            score_weighting=result['score_weighting'],
            long_tail_summaries=[{k: c[k] for k in ('option_index', 'action', 'card',
                'top_expected_hp_loss', 'bottom_expected_hp_loss', 'long_expected_hp_loss',
                'top_leaf_count', 'bottom_leaf_count', 'selected_leaf_count')}
                for c in result['candidates']])
        return result

    def cards(self, state, options, raw, build, *, fixed_depth=None):
        explicit, mapping, projected_noops = [], [], []
        skip = next((o['index'] for o in options if o['kind'] in ('skip', 'leave') or
                     (o['kind'] == 'alternative' and o.get('id', '').upper() == 'SKIP')), None)
        for option in options:
            if option['kind'] != 'card': continue
            action = option.get('action', 'take')
            card = option['card']
            if card['id'] not in self.model.catalog.cards or card['id'] in self.model.catalog.excluded['cards']:
                self.model.warnings.append(f'unscored_{action}:' + card['id'])
                if action in ('remove', 'upgrade'):
                    # This owned instance was omitted from model input. Its
                    # original index must never alias a different modeled card.
                    projected_noops.append(option['index'])
                continue
            row = dict(action=action, card=normalize_card(card))
            if action in ('upgrade', 'remove'):
                index = option['deckIndex']
                row['deck_index'] = sum(c['id'] in self.model.catalog.cards and c['id'] not in self.model.catalog.excluded['cards']
                                        for c in raw['cards'][:index])
            explicit.append(row); mapping.append(option['index'])
        if not explicit:
            if skip is not None: return skip
            # Forced out-of-domain offers have no modeled score. Keep the
            # run legal with a declared deterministic choice, not a fake score.
            self.model.warnings.append('forced_unmodeled_card_choice')
            return options[0]['index']
        result = self.search_card_builds(state, build, explicit, fixed_depth=fixed_depth)
        crisis = self.last_report['crisis']
        scores = {original: result['candidates'][i]['combined_score'] for i, original in enumerate(mapping)}
        scores.update((i, result['candidates'][-1]['combined_score']) for i in projected_noops)
        if skip is not None: scores[skip] = result['candidates'][-1]['combined_score']
        # Other explicit alternatives are not silently converted into skip.
        # Heal/sacrifice/reroll receive an explicit resource heuristic.
        for option in options:
            if option['kind'] == 'alternative' and option['index'] not in scores:
                gain = min(2, state['maxHp']-state['hp']) if 'HEAL' in option.get('id', '').upper() else .1
                scores[option['index']] = result['candidates'][-1]['combined_score'] + gain
        self.last_report.update(scores=scores, skip_score=result['candidates'][-1]['combined_score'])
        # Filter taking cards before comparing other legal alternatives. A
        # blocked card must not hide a useful free heal or a free upgrade.
        margin = self.config['crisis_card_min_gain'] if crisis else self.config['normal_card_min_gain']
        eligible = {i: score for i, score in scores.items()
                    if skip is None or options[i]['kind'] != 'card'
                    or options[i].get('action', 'take') != 'take'
                    or score > scores[skip] + margin}
        self.last_report.update(card_min_gain=margin, threshold_rejected=[i for i in scores if i not in eligible])
        return max(eligible, key=lambda i: (eligible[i], i == skip, -i))

    def candidate(self, raw, option, context=None):
        value = deepcopy(raw)
        value['relics'] = list(value['relics'])
        value['ancient_history'] = list(value['ancient_history'])
        kind = option['kind']
        if kind == 'relic':
            relic = deepcopy(option['relic'])
            if not any(r['id'] == relic['id'] for r in value['relics']): value['relics'].append(relic)
            if relic['id'] == 'TOUCH_OF_OROBAS':
                # Public deterministic acquisition effect for Silent. This is
                # a candidate projection; the actual replacement is native.
                for i, owned in enumerate(value['relics']):
                    if owned['id'] == 'RING_OF_THE_SNAKE':
                        value['relics'][i] = dict(id='RING_OF_THE_DRAKE', state=[])
            event_id = (context or {}).get('eventId')
            if event_id in self.model.catalog.ancients and len(value['ancient_history']) < value['act']:
                value['ancient_history'].append([value['act'], event_id, relic['id']])
        elif kind == 'bundle': value['cards'].extend(deepcopy(option['cards']))
        elif kind == 'card':
            action = option.get('action', 'take')
            index = option.get('deckIndex', -1)
            if action == 'take': value['cards'].append(deepcopy(option['card']))
            elif action in ('remove', 'transform'):
                if index < 0: raise ValueError('Card operation is not an owned instance')
                value['cards'].pop(index)
            elif action == 'upgrade': value['cards'][index] = deepcopy(option['card'])
            elif action == 'enchant':
                effect = context['effect']
                if index < 0: raise ValueError('Enchant target is not an owned instance')
                card = value['cards'][index]
                if card.get('enchantment_id', '') not in ('', effect['id']):
                    raise ValueError('Cannot replace a different existing enchantment')
                card.update(enchantment_id=effect['id'],
                            enchantment_amount=card.get('enchantment_amount', 0)+effect['amount'])
            elif action != 'select': raise ValueError('Unknown card action: ' + action)
        return self.model.project(value)

    def event(self, state, options, context):
        if context['eventId'] == 'DOLL_ROOM':
            options, reason = doll_room_options(options)
            self.last_report.update(reason=reason, allowed_options=[o['index'] for o in options])
            if len(options) == 1:
                return options[0]['index']
        raw = self.raw_build(state)
        scores, reasons = {}, {}
        ancient = context['eventId'] in self.model.catalog.ancients
        baseline = None if ancient else self.model.score([self.model.project(raw)], self.targets(state), state['maxHp'])[0]['expected_hp_loss']
        relic_options = [o for o in options if o.get('relic')]
        if relic_options:
            builds = [self.candidate(raw, o, context) for o in relic_options]
            results = self.model.score(builds, self.targets(state), state['maxHp'])
            scores.update((o['index'], (baseline or 0)-r['expected_hp_loss']) for o, r in zip(relic_options, results))
            reasons.update((o['index'], 'immediate_relic_model') for o in relic_options)
        for option in options:
            if option['index'] not in scores:
                scores[option['index']], reasons[option['index']] = event_value(context['eventId'], option, state, self.config)
            key = option.get('id', '').upper().split('.')[-1]
            if context['eventId'] == 'THIS_OR_THAT' and key == 'ORNATE':
                # The random relic remains unknown. Only the explicitly shown
                # curse can be projected, with a declared random-relic prior.
                candidate_raw = deepcopy(raw)
                candidate_raw['cards'].append(dict(id='CLUMSY'))
                candidate = self.model.project(candidate_raw)
                scores[option['index']] = self.config['event_relic_value'] + baseline - self.model.score([candidate], self.targets(state), state['maxHp'])[0]['expected_hp_loss']
                reasons[option['index']] = 'public_clumsy_effect_and_unknown_relic_prior'
            if option.get('lethal'):
                scores[option['index']], reasons[option['index']] = -1e9, 'visible_lethal_option'
        options_by_index = {o['index']: o for o in options}
        rejected = adjust_event_cards(self, state, options, context, raw, scores, reasons)
        self.last_report.update(scores=scores, reasons=reasons)
        return max((i for i in scores if i not in rejected),
                   key=lambda i: (scores[i], options_by_index[i].get('proceed', False), -i))

    def immediate(self, state, options, raw, build, screen, context):
        targets = self.targets(state)
        baseline = self.model.score([build], targets, state['maxHp'])[0]['expected_hp_loss']
        scores = {}
        card_gains = {}
        if screen == 'SHOP' and any(o['kind'] == 'card' for o in options):
            self.cards(state, options, raw, build)
            card_report = deepcopy(self.last_report)
            if 'skip_score' in card_report:
                card_gains = {i: score-card_report['skip_score'] for i, score in card_report['scores'].items()}
            self.last_report['card_search'] = card_report
        for option in options:
            kind = option['kind']; gain = 0.
            if kind in ('card', 'bundle', 'relic'):
                if option['index'] in card_gains:
                    gain = card_gains[option['index']]
                    margin = self.config['crisis_card_min_gain'] if self.last_report.get('crisis') else self.config['normal_card_min_gain']
                    if gain <= margin:
                        # A hard eligibility rule, independent of gold tuning.
                        scores[option['index']] = -1e9
                        continue
                else:
                    candidate = self.candidate(raw, option, context)
                    gain = baseline - self.model.score([candidate], targets, state['maxHp'])[0]['expected_hp_loss']
                if kind == 'card' and option.get('action') == 'transform':
                    self.model.warnings.append('transform_uses_removal_heuristic_without_peeking_result')
                if kind == 'card' and option.get('action') == 'select':
                    self.model.warnings.append('unspecified_card_selection_heuristic')
                if kind == 'relic': gain += .01  # free ties favor taking a normal relic
                if kind == 'card' and option['card']['id'] in self.model.catalog.excluded['cards']: gain = -1e6
            elif kind == 'gold': gain = option['amount'] * self.config['gold_hp_value']
            elif kind == 'open_cards': gain = 10
            elif kind in ('potion', 'potion_replace'):
                if kind == 'potion_replace' and screen != 'REWARDS':
                    raise ValueError('Potion replacement is only supported for free rewards')
                gain = self.config['potion_value'] if potion_reward_eligible(option, state['potions'], self.config) else -1e9
            elif kind == 'remove': gain = self.config['shop_remove_value']  # actual instance is scored on the child screen
            elif kind == 'reward': gain = 1
            elif kind not in ('skip', 'leave'): raise ValueError('Unsupported choice kind: ' + kind)
            if screen == 'SHOP' and kind != 'leave':
                gain -= option.get('price', 0)*self.config['gold_hp_value']
                if state['gold']-option.get('price', 0) < self.config['shop_reserve_gold']: gain -= 1
            scores[option['index']] = gain
        self.last_report.update(scores=scores, reason='immediate_model_and_visible_resources')
        eligible = dict(scores)
        if screen == 'SHOP':
            leave_score = max((scores[o['index']] for o in options if o['kind'] == 'leave'), default=0.)
            # Revisit the shop after every purchase. Potions only compete once
            # all currently worthwhile, affordable card purchases are exhausted.
            cards_first = any(o['kind'] == 'card' and scores[o['index']] > leave_score for o in options)
            deferred = [o['index'] for o in options if cards_first and o['kind'] == 'potion']
            for index in deferred:
                eligible.pop(index)
            self.last_report['potions_deferred_for_cards'] = deferred
            worthwhile = {o['kind'] for o in options if o['index'] in eligible
                          and eligible[o['index']] > leave_score}
            if {'remove', 'potion'} <= worthwhile:
                if 'crisis' not in self.last_report:
                    self.search_card_builds(state, build, [])
                deferred_kind = 'remove' if self.last_report['crisis'] else 'potion'
                deferred = [o['index'] for o in options if o['kind'] == deferred_kind]
                for index in deferred:
                    eligible.pop(index, None)
                self.last_report.update(shop_resource_priority='potion_before_remove' if self.last_report['crisis']
                                        else 'remove_before_potion', resource_priority_deferred=deferred)
        selected = max(eligible, key=lambda i: (eligible[i], options[i]['kind'] in ('skip', 'leave'),
            potion_priority(options[i]['id'], self.config)
                if screen == 'REWARDS' and options[i]['kind'] in ('potion', 'potion_replace') else 0, -i))
        if options[selected]['kind'] in ('potion', 'potion_replace'):
            self.last_report['potion_choice'] = options[selected]
        return selected
