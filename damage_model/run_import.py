"""Reconstruct v0.111.0 run histories without treating human damage as a label.

Histories aggregate changes within a floor, and upgrades identify a card type,
not an instance. Keep all consistent interpretations, validate the final deck,
and accept a precombat deck only when the surviving interpretations agree.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from itertools import permutations
import json
from pathlib import Path
import time

from .catalog import COUNTER_DOMAINS
from .schema import Build, Card, Relic, canonical, digest
from .starter_relics import SNAKE, DRAKE, TOUCH, uses_orobas_replacement
from .card_state import normalize_extra, parse_props, history_progress, SPECIAL_POOLS
from .target_scope import WINDOW_POLICY, require_policy, recorded_floors, window_for_origin, save_target_origins

IMPORT_VERSION = "spire_codex_run_v1"
IMPORT_REVISION = 'special_cards_saved_state_v8'
OROBAS_REVISION = 'orobas_starter_replacement_v7'
PREVIOUS_IMPORT_REVISION = 'relic_pickup_normalization_v4'
SHARED_ANCIENT_REVISION = 'shared_ancient_provenance_v5'
REMOVED_RELIC_REVISION = 'potion_revival_relic_normalization_v6'
REPROCESS_REVISIONS = {'enchantments_counters_v2', 'max_hp_relic_normalization_v3',
                      PREVIOUS_IMPORT_REVISION, SHARED_ANCIENT_REVISION, REMOVED_RELIC_REVISION, OROBAS_REVISION}
MAX_INTERPRETATIONS = 256
LEGACY_PRESENTATION_FIELDS = {'run_hash', 'username', 'has_replay', 'damage', 'player_index'}
PRESENTATION_FIELDS = LEGACY_PRESENTATION_FIELDS | {'is_beta', '_spirecodex_damage'}


def source_checksum(run, *, legacy=False):
    """Only explicit API metadata differs between shared and export payloads.

    The shared endpoint derives is_beta from build_id and rewrites the optional
    raw DPS payload to damage. Game version, players and history remain hashed.
    """
    import hashlib
    ignored = LEGACY_PRESENTATION_FIELDS if legacy else PRESENTATION_FIELDS
    return hashlib.sha256(canonical({k:v for k,v in run.items() if k not in ignored}).encode()).hexdigest()


class RunRejected(ValueError):
    """A documented source limitation, never a simulated combat failure."""


def entry(value, category):
    if not isinstance(value, str) or not value.startswith(category + '.'):
        raise RunRejected(f'Invalid {category} identifier')
    return value.split('.', 1)[1]


@dataclass(frozen=True, order=True)
class HistoryCard:
    id: str
    upgrade: int
    floor: int
    extra: str = '{}'

    @classmethod
    def read(cls, value, floor=None):
        upgrade = value.get('current_upgrade_level', 0)
        acquired = value.get('floor_added_to_deck', 0) if floor is None else floor
        if type(upgrade) is not int or upgrade < 0 or type(acquired) is not int:
            raise RunRejected('Invalid card upgrade/acquisition floor')
        extra = {k:v for k,v in value.items() if k not in
                 ('id', 'current_upgrade_level', 'floor_added_to_deck')}
        card_id = entry(value['id'], 'CARD')
        try:
            extra = normalize_extra(card_id, extra, historical=True)
        except ValueError as error:
            raise RunRejected(str(error)) from error
        return cls(card_id, upgrade, acquired, canonical(extra))


def signature(deck):
    # Acquisition floor identifies historical instances but is not a model input.
    return tuple(sorted((c.id, c.upgrade, c.extra) for c in deck))


def apply_one(deck, kind, value, floor, catalog):
    if kind == 'gain':
        return {tuple(sorted((*deck, HistoryCard.read(value, floor))))}
    outcomes = set()
    for i, card in enumerate(deck):
        new_card = None
        if kind in ('upgrade', 'downgrade'):
            if card.id != entry(value, 'CARD'):
                continue
            amount = 1 if kind == 'upgrade' else -1
            maximum = catalog.cards.get(card.id, {}).get('max_upgrade_level')
            if maximum is None or not 0 <= card.upgrade + amount <= maximum:
                continue
            new_card = replace(card, upgrade=card.upgrade + amount)
        elif kind in ('remove', 'transform'):
            original = HistoryCard.read(value if kind == 'remove' else value['original_card'])
            if card != original:
                continue
            if kind == 'transform':
                new_card = HistoryCard.read(value['final_card'], floor)
        elif kind == 'enchant':
            enchanted = HistoryCard.read(value['card'])
            # Match forward against the surviving historical instances. A record
            # may repeat the enchanted state of a newly gained card; this is not
            # an instruction to apply the enchantment a second time.
            if (card.id, card.upgrade, card.floor) != (enchanted.id, enchanted.upgrade, enchanted.floor):
                continue
            previous_extra, next_extra = json.loads(card.extra), json.loads(enchanted.extra)
            previous_enchantment = previous_extra.pop('enchantment', None)
            next_enchantment = next_extra.pop('enchantment', None)
            if previous_extra != next_extra or not next_enchantment:
                continue
            if value.get('enchantment') != next_enchantment.get('id'):
                continue
            if previous_enchantment and previous_enchantment != next_enchantment:
                continue
            new_card = enchanted
        else:
            raise AssertionError(kind)
        updated = deck[:i] + deck[i+1:] + (() if new_card is None else (new_card,))
        outcomes.add(tuple(sorted(updated)))
    return outcomes


def apply_floor(deck, stats, floor, catalog):
    groups = [(kind, stats.get(field, [])) for kind, field in (
        ('gain', 'cards_gained'), ('remove', 'cards_removed'),
        ('transform', 'cards_transformed'), ('upgrade', 'upgraded_cards'),
        ('downgrade', 'downgraded_cards'), ('enchant', 'cards_enchanted'))
        if stats.get(field)]
    results = set()
    # Ordering between categories is absent from .run. Do not invent it.
    for order in permutations(groups):
        states = {deck}
        for kind, changes in order:
            for value in changes:
                states = {next_deck for current in states
                          for next_deck in apply_one(current, kind, value, floor, catalog)}
                if len(states) > MAX_INTERPRETATIONS:
                    raise RunRejected('Too many ambiguous card histories')
        results.update(states)
        if len(results) > MAX_INTERPRETATIONS:
            raise RunRejected('Too many ambiguous card histories')
    return results


def enter_history_floor(deck, stats, node, floor, catalog):
    """Dowsing advances before the first room; its fifth step transforms before combat."""
    if node.get('map_point_type') != 'unknown':
        return deck, stats
    deck = tuple(sorted(history_progress(c, 'RoomsEntered') if c.id == 'DOWSING' else c for c in deck))
    transformations = list(stats.get('cards_transformed', []))
    for card in tuple(deck):
        if card.id != 'DOWSING' or dict(parse_props(card.id, json.loads(card.extra).get('props'), historical=True)).get('RoomsEntered', 0) != 5:
            continue
        matches = [x for x in transformations if HistoryCard.read(x['original_card']) == card
                   and x['final_card']['id'] == 'CARD.ABUNDANCE']
        if len(matches) != 1:
            raise RunRejected('Missing Dowsing completion history')
        result = apply_one(deck, 'transform', matches[0], floor, catalog)
        if len(result) != 1:
            raise RunRejected('Ambiguous Dowsing completion history')
        deck = next(iter(result)); transformations.remove(matches[0])
    return deck, {**stats, 'cards_transformed': transformations}


def leave_history_combat(deck, node, stats, *, last_floor, run):
    combats = [room for room in node.get('rooms', []) if str(room.get('model_id', '')).startswith('ENCOUNTER.')]
    if not combats or not any(c.id == 'GUILTY' for c in deck):
        return deck
    if len(node.get('rooms', [])) != 1:
        raise RunRejected('Guilty progress in a mixed combat room remains ambiguous')
    # Defeat does not finish combat successfully or invoke AfterCombatEnd.
    if last_floor and not run.get('win') and stats.get('current_hp', 0) <= 0:
        return deck
    return tuple(sorted(history_progress(c, 'CombatsSeen') if c.id == 'GUILTY' else c for c in deck))


def check_run(run):
    if run.get('schema_version') != 10 or run.get('build_id') != 'v0.111.0':
        raise RunRejected('Unsupported run schema/game version')
    if run.get('ascension') != 10 or run.get('game_mode') != 'standard' or run.get('modifiers'):
        raise RunRejected('Requires standard A10 without modifiers')
    players = run.get('players', [])
    if len(players) != 1 or players[0].get('character') != 'CHARACTER.SILENT':
        raise RunRejected('Requires solo Silent')
    if not run.get('map_point_history'):
        raise RunRejected('No floor history')
    return players[0]


def reconstruct(run, catalog):
    player = check_run(run)
    for relic in player['relics']:
        if relic['id'] == 'RELIC.' + TOUCH and relic.get('props'):
            props = relic['props']
            values = props.get('model_ids', [])
            if (set(props) != {'model_ids'} or len(values) != 2
                    or {v['name']: v['value'] for v in values} != {
                        'StarterRelic': 'RELIC.' + SNAKE, 'UpgradedRelic': 'RELIC.' + DRAKE}):
                raise RunRejected('Unsupported Touch of Orobas saved replacement')
    deck = tuple(sorted(HistoryCard(c, 0, 1) for c in
                 (*catalog.raw['character']['starting_deck'], 'ASCENDERS_BANE')))
    # Each interpretation keeps its earlier observations for final-deck validation.
    traces = {(deck, ())}
    relics = list(catalog.raw['character']['starting_relics'])
    ancient_history, floors = [], []
    floor = 0
    total_floors = sum(len(nodes) for nodes in run['map_point_history'])
    for act_index, nodes in enumerate(run['map_point_history']):
        act_id = entry(run['acts'][act_index], 'ACT')
        for node in nodes:
            floor += 1
            stats_list = [s for s in node['player_stats'] if s['player_id'] == player['id']]
            if len(stats_list) != 1:
                raise RunRejected('Missing or duplicate player floor stats')
            stats = stats_list[0]
            rooms = node.get('rooms', [])
            encounters = [r for r in rooms if str(r.get('model_id', '')).startswith('ENCOUNTER.')]
            floors.append({'floor': floor, 'act': act_index+1, 'act_id': act_id,
                'target': entry(encounters[0]['model_id'], 'ENCOUNTER') if len(encounters)==1 else None,
                'simple_combat': len(rooms)==1 and len(encounters)==1,
                'relics': tuple(relics), 'ancient_history': tuple(ancient_history),
                'historical_max_hp': stats.get('max_hp'),
                'room_types': [r.get('room_type') for r in rooms]})
            next_traces = set()
            for current, history in traces:
                precombat, remaining = enter_history_floor(current, stats, node, floor, catalog)
                settled = leave_history_combat(precombat, node, stats, last_floor=floor == total_floors, run=run)
                for after in apply_floor(settled, remaining, floor, catalog):
                    next_traces.add((after, history + (precombat,)))
                    if len(next_traces) > MAX_INTERPRETATIONS:
                        raise RunRejected(f'Ambiguous card history exceeds bound at floor {floor}')
            if not next_traces:
                raise RunRejected(f'Card changes cannot be reconciled at floor {floor}')
            traces = next_traces
            gains = list(dict.fromkeys(
                [entry(x['choice'], 'RELIC') for x in stats.get('relic_choices', []) if x.get('was_picked')]
                + [entry(x, 'RELIC') for x in stats.get('bought_relics', [])]))
            removed = [entry(x, 'RELIC') for x in stats.get('relics_removed', [])]
            if set(gains) & set(removed):
                raise RunRejected('Relic acquisition/removal order is ambiguous')
            replacement = TOUCH in gains
            if replacement and (SNAKE not in relics or SNAKE not in removed or DRAKE not in gains
                    or DRAKE in relics or TOUCH in relics
                    or not any(x.get('was_chosen') and x.get('TextKey') == TOUCH
                               for x in stats.get('ancient_choice', []))
                    or [r.get('model_id') for r in rooms] != ['EVENT.OROBAS']
                    or act_index != 1):
                raise RunRejected('Unsupported Touch of Orobas replacement history')
            for r in removed:
                if r not in relics:
                    raise RunRejected('Removed relic was not owned')
                if replacement and r == SNAKE:
                    # RelicCmd.Replace inserts the replacement at the old index.
                    relics[relics.index(SNAKE)] = DRAKE
                else:
                    relics.remove(r)
            for r in gains:
                if replacement and r == DRAKE:
                    continue
                if r in relics:
                    raise RunRejected('Duplicate relic acquisition')
                relics.append(r)
            if stats.get('ancient_choice'):
                events = [entry(r['model_id'], 'EVENT') for r in rooms
                          if str(r.get('model_id', '')).startswith('EVENT.')]
                choices = [x for x in stats['ancient_choice'] if x.get('was_chosen')]
                if len(events) != 1 or len(choices) != 1:
                    raise RunRejected('Ambiguous ancient provenance')
                chosen = choices[0].get('TextKey')
                if chosen not in gains:
                    raise RunRejected('Ancient choice does not identify its acquired relic')
                ancient_history.append((act_index+1, events[0], chosen))
    final = tuple(sorted(HistoryCard.read(c) for c in player['deck']))
    survivors = [history for current, history in traces if current == final]
    if not survivors:
        raise RunRejected('Reconstructed final deck does not match the run')
    if relics != [entry(r['id'], 'RELIC') for r in player['relics']]:
        raise RunRejected('Reconstructed final relic order/inventory does not match the run')
    for i, details in enumerate(floors):
        states = {signature(trace[i]) for trace in survivors}
        details['cards'] = next(iter(states)) if len(states) == 1 else None
    return floors


def build_for(snapshot, run_hash, catalog):
    if not snapshot['simple_combat']:
        raise RunRejected('Not a single recorded combat room')
    if snapshot['cards'] is None:
        raise RunRejected('Precombat card state remains ambiguous')
    cards = tuple(import_card(c, u, extra) for c, u, extra in snapshot['cards'])
    source_relics = snapshot['relics']
    # Validate before stripping even if nothing is removed from this inventory:
    # a removed-relic policy cannot excuse a reward never present in the source.
    catalog.validate_ancient_history(snapshot['act'], snapshot['ancient_history'], source_relics)
    kept_relics = tuple(r for r in source_relics if r not in catalog.normalized_relic_ids)
    # The user's policy: real inventory, sampled legal counters, reproducible per
    # inventory. Repeated floors/runs with identical inputs do not spawn new jobs.
    counter_seed = digest([IMPORT_VERSION, catalog.config['counter_seed'], snapshot['act_id'],
                           snapshot['cards'], kept_relics])
    relics = []
    for rid in kept_relics:
        state = []
        for key, domain in sorted(COUNTER_DOMAINS.get(rid, {}).items()):
            index = int(digest([counter_seed, rid, key])[:16], 16) % len(domain)
            state.append((key, domain[index]))
        if rid == 'WONGOS_MYSTERY_TICKET':
            state = [('CombatsFinished', dict(state)['CombatsFinished']),
                     ('GaveRelic', dict(state)['CombatsFinished'] >= 5)]
        relics.append(Relic(rid, tuple(state)))
    build = Build(snapshot['act_id'], snapshot['act'], cards, tuple(relics),
                  snapshot['ancient_history'], family='run:'+run_hash,
                  mutation=IMPORT_VERSION)
    catalog.validate(build)
    if snapshot['target'] not in {t['id'] for t in catalog.targets(build)}:
        raise RunRejected('Recorded encounter is not in the current act catalog')
    # The native fixture starts with Snake. The explicit Orobas adapter replaces
    # it in place through RelicCmd; other starter changes remain unsupported.
    if not uses_orobas_replacement([r.id for r in build.relics], build.ancient_history) and (
            not build.relics or build.relics[0].id != SNAKE):
        raise RunRejected('Starter relic replacement is not supported by the native fixture')
    return build, counter_seed


def import_card(card_id, upgrade, extra):
    props = json.loads(extra)
    enchantment = props.pop('enchantment', None)
    try:
        state = parse_props(card_id, props.pop('props', None))
    except ValueError as error:
        raise RunRejected(str(error)) from error
    if props:
        raise RunRejected('Unsupported persistent card state: ' + ','.join(sorted(props)))
    if enchantment is None:
        return Card(card_id, upgrade, persistent_state=state)
    if not isinstance(enchantment, dict) or set(enchantment) != {'id', 'amount'}:
        raise RunRejected('Unsupported enchantment state')
    if type(enchantment['amount']) is not int or enchantment['amount'] <= 0:
        raise RunRejected('Invalid enchantment amount')
    return Card(card_id, upgrade, entry(enchantment['id'], 'ENCHANTMENT'), enchantment['amount'], state)


def init_sources(store):
    store.db.executescript('''
        CREATE TABLE IF NOT EXISTS source_runs(
            hash TEXT PRIMARY KEY, sha256 TEXT NOT NULL, version TEXT NOT NULL,
            source TEXT NOT NULL, body TEXT NOT NULL, report TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS build_origins(
            build_id TEXT NOT NULL, run_hash TEXT NOT NULL, floor INTEGER NOT NULL,
            details TEXT NOT NULL, PRIMARY KEY(build_id,run_hash,floor));
        CREATE INDEX IF NOT EXISTS origins_run ON build_origins(run_hash);
        CREATE TABLE IF NOT EXISTS source_import_history(
            hash TEXT NOT NULL, version TEXT NOT NULL, report TEXT NOT NULL,
            recorded_at REAL NOT NULL, PRIMARY KEY(hash,version));
        CREATE TABLE IF NOT EXISTS source_equivalences(
            hash TEXT NOT NULL,payload_sha256 TEXT NOT NULL,gameplay_sha256 TEXT NOT NULL,
            policy TEXT NOT NULL,source TEXT NOT NULL,body TEXT NOT NULL,recorded_at REAL NOT NULL,
            PRIMARY KEY(hash,payload_sha256));
    ''')


def import_run(store, catalog, teacher, run, run_hash, source, *, reprocess=False):
    import hashlib
    if any(json.loads(r[0]).get('mutation') != IMPORT_VERSION
           for r in store.db.execute('SELECT body FROM builds')):
        raise ValueError('Real runs require a separate database; preserve the synthetic dataset')
    init_sources(store)
    target_policy = require_policy(store, catalog.config)
    checksum = source_checksum(run)
    previous = store.db.execute('SELECT sha256,version,report,body FROM source_runs WHERE hash=?', (run_hash,)).fetchone()
    if previous:
        original = json.loads(previous['body'])
        original_checksum = source_checksum(original)
        if previous['sha256'] not in {original_checksum, source_checksum(original, legacy=True)}:
            raise ValueError('Stored source checksum does not match its original payload')
        if original_checksum != checksum:
            raise ValueError('Source content/import version changed; use a new dataset')
        # Preserve the original row/checksum and the full equivalent incoming
        # payload; never rewrite a historical source or turn human DPS into labels.
        incoming = canonical(run)
        if previous['body'] != incoming:
            with store.db:
                store.db.execute('INSERT OR IGNORE INTO source_equivalences VALUES(?,?,?,?,?,?,?)',
                    (run_hash, hashlib.sha256(incoming.encode()).hexdigest(), checksum,
                     'spire_codex_metadata_v2', source, incoming, time.time()))
        if previous['version'] == IMPORT_REVISION:
            return {**json.loads(previous['report']), 'already_imported': True, 'scheduled_now': 0}
        if previous['version'] in {PREVIOUS_IMPORT_REVISION, SHARED_ANCIENT_REVISION, REMOVED_RELIC_REVISION, OROBAS_REVISION} and not reprocess:
            # Re-audit cached sources affected by a newly removed relic, or by
            # v5's shared-Ancient correction. Unaffected old rows stay verbatim.
            shared_events = {'EVENT.' + a for a in catalog.shared_ancients}
            shared_affected = previous['version'] == PREVIOUS_IMPORT_REVISION and any(room.get('model_id') in shared_events
                           for act in run.get('map_point_history', []) for floor in act
                           for room in floor.get('rooms', []))
            skipped = json.loads(previous['report']).get('skipped', {})
            removal_affected = any('Disallowed relic: ' + rid in skipped
                                  for rid in catalog.explicitly_removed_relics)
            replacement_affected = any(x.get('was_picked') and x.get('choice') == 'RELIC.' + TOUCH
                for act in run.get('map_point_history', []) for floor in act
                for stats in floor.get('player_stats', []) for x in stats.get('relic_choices', []))
            special_ids = {c['id'] for c in catalog.raw['cards'] if c['pool'] in SPECIAL_POOLS} | {'DOWSING', 'GUILTY', 'MAD_SCIENCE', 'SPOILS_MAP'}
            cards_affected = any('CARD.' + cid in incoming for cid in special_ids)
            if not (shared_affected or removal_affected or replacement_affected or cards_affected):
                return {**json.loads(previous['report']), 'already_imported': True, 'scheduled_now': 0}
            reprocess = True
        if not reprocess or previous['version'] not in REPROCESS_REVISIONS:
            raise ValueError('Source import version changed; explicitly reprocess the supported revision')
    report = {'run_hash': run_hash, 'accepted_floors': 0, 'skipped': {}, 'scheduled_now': 0,
              'target_policy': target_policy,
              'counter_policy': 'sample_legal_domains_v2', 'version': IMPORT_REVISION,
              'max_hp_relic_policy': 'remove' if catalog.remove_max_hp_relics else 'reject_build',
              'normalized_floors': 0, 'removed_max_hp_relics': {}, 'removed_user_relics': {}}
    skipped = Counter()
    removed = Counter()
    removed_user = Counter()
    try:
        snapshots = reconstruct(run, catalog)
    except (RunRejected, KeyError, IndexError, TypeError) as error:
        report['rejected'] = str(error)
        snapshots = []
    seeds = [digest(['battle', catalog.config['battle_seed'], j])[:16]
             for j in range(catalog.config['initial_seeds_per_pair'])]
    source_floors = recorded_floors(run) if snapshots and target_policy['name'] == WINDOW_POLICY else None
    for state in snapshots:
        if state['target'] is None:
            continue
        try:
            build, counter_seed = build_for(state, run_hash, catalog)
        except ValueError as error:
            skipped[str(error)] += 1
            continue
        # Deduplicate the native work across runs, while retaining every origin.
        targets = catalog.targets(build)
        selection = None
        if source_floors is not None:
            targets, selection = window_for_origin(source_floors, state, catalog, target_policy['radius'])
        report['scheduled_now'] += store.schedule(build, targets, seeds, teacher,
                                                reactivate_excluded=selection is not None)
        details = {k:v for k,v in state.items() if k != 'cards'}
        details['counter_seed'] = counter_seed
        stripped = [r for r in state['relics'] if r not in {relic.id for relic in build.relics}]
        stripped_hp = [r for r in stripped if r in catalog.max_hp_relic_ids]
        stripped_user = [r for r in stripped if r in catalog.explicitly_removed_relics]
        details['normalization'] = {'revision': IMPORT_REVISION, 'removed_max_hp_relics': stripped_hp,
                                    'removed_user_relics': stripped_user,
                                    'initial_hp': 70, 'initial_max_hp': 70}
        if stripped:
            removed.update(stripped_hp)
            removed_user.update(stripped_user)
            report['normalized_floors'] += 1
        with store.db:
            store.db.execute('INSERT OR IGNORE INTO build_origins VALUES(?,?,?,?)',
                             (build.id, run_hash, state['floor'], canonical(details)))
            if selection is not None:
                save_target_origins(store.db, build.id, run_hash, selection)
        if selection and selection['skipped']:
            report.setdefault('skipped_neighbor_targets', []).append(selection)
        report['accepted_floors'] += 1
    report['skipped'] = dict(skipped)
    report['removed_max_hp_relics'] = dict(removed)
    report['removed_user_relics'] = dict(removed_user)
    with store.db:
        if previous:
            store.db.execute('INSERT OR IGNORE INTO source_import_history VALUES(?,?,?,?)',
                (run_hash, previous['version'], previous['report'], time.time()))
            store.db.execute('UPDATE source_runs SET version=?,report=? WHERE hash=?',
                (IMPORT_REVISION, canonical(report), run_hash))
        else:
            store.db.execute('INSERT INTO source_runs VALUES(?,?,?,?,?,?)',
                (run_hash, checksum, IMPORT_REVISION, source, canonical(run), canonical(report)))
    return report


def import_files(store, catalog, teacher, directory):
    reports = []
    for path in sorted(Path(directory).glob('*.run')):
        run = json.loads(path.read_text(encoding='utf-8'))
        run_hash = run.get('run_hash', path.stem)
        reports.append(import_run(store, catalog, teacher, run, run_hash,
                                 'https://spire-codex.com/api/runs/shared/'+run_hash))
    return reports


def source_groups(database):
    """Run-connected components keep a shared build and all its source runs together.

This is calculated for a training snapshot, without rewriting source records.
If a giant connected component leaves insufficient holdout data, training must
refuse rather than split the same run across training and evaluation.
"""
    if not database.execute("SELECT 1 FROM sqlite_master WHERE name='build_origins'").fetchone():
        return {}
    origins = list(database.execute('SELECT build_id,run_hash FROM build_origins'))
    parent = {}
    def root(x):
        parent.setdefault(x,x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    owners = {}
    for build, run in origins:
        if build in owners:
            a,b = root(run),root(owners[build])
            parent[max(a,b)] = min(a,b)
        else:
            owners[build] = run
            root(run)
    groups = {}
    for run in parent:
        groups.setdefault(root(run),[]).append(run)
    families = {group:'run-component:'+digest(sorted(runs)) for group,runs in groups.items()}
    return {build:families[root(run)] for build,run in owners.items()}
