"""Reproducible one-generation neighbours of verified real-run inventories."""
from collections import Counter, defaultdict
from dataclasses import asdict, replace
import json
import random
import time

from .catalog import COUNTER_DOMAINS, validate_counter_relation
from .schema import Build, Card, Relic, canonical, digest

MUTATION = 'real_run_mutation_v1'
TARGET_POLICY = {'name': 'parent_source_window_v1', 'radius': 2, 'same_act': True,
                 'parent_policy': 'source_floor_window_v1'}
ORDINARY = {'Common', 'Uncommon', 'Rare', 'Shop'}


def require_mutation_database(db):
    row = db.execute("SELECT value FROM collection_settings WHERE key='mutation_policy'").fetchone()
    if row is None or json.loads(row[0]).get('name') != MUTATION:
        raise ValueError('Not an initialized mutation database')
    policy = db.execute("SELECT value FROM collection_settings WHERE key='target_policy'").fetchone()
    if policy is None or json.loads(policy[0]) != TARGET_POLICY:
        raise ValueError('Mutation target policy differs')


def validate_policy(policy):
    if (policy['name'] != MUTATION or policy['generation_depth'] != 1
            or policy['map_weights'] != {'GLORY': .6, 'HIVE': .4}
            or policy['small_probability'] not in (.8, .6)
            or policy['small'] != {'cards': [1, 2], 'relics': [1, 2]}
            or policy['large'] != {'cards': [3, 6], 'relics': [1, 4]}
            or policy['axes_weights'] != {'cards': 1, 'relics': 1, 'both': 1}):
        raise ValueError('Mutation policy differs from the approved first round')


def policy_history(db):
    current = json.loads(db.execute("SELECT value FROM collection_settings WHERE key='mutation_policy'").fetchone()[0])
    row = db.execute("SELECT value FROM collection_settings WHERE key='mutation_policy_history'").fetchone()
    history = json.loads(row[0]) if row else [
        {'start_sequence': 0, 'policy': current, 'reason': 'Initial generation policy'}]
    if not history or history[0]['start_sequence'] != 0:
        raise ValueError('Mutation policy history must begin at sequence zero')
    prior = -1
    for entry in history:
        validate_policy(entry['policy'])
        if not isinstance(entry['start_sequence'], int) or entry['start_sequence'] <= prior:
            raise ValueError('Mutation policy history is not ordered')
        if {k: v for k, v in entry['policy'].items() if k != 'small_probability'} != {
                k: v for k, v in current.items() if k != 'small_probability'}:
            raise ValueError('Only mutation size probability may change within this batch')
        prior = entry['start_sequence']
    sequence = json.loads(db.execute("SELECT value FROM collection_settings WHERE key='mutation_sequence'").fetchone()[0])
    if history[-1]['policy'] != current or prior > sequence:
        raise ValueError('Mutation policy history differs from the active generation policy')
    return history


def change_size_probability(store, policy, reason):
    """Change only future sampling, preserving the policy for every old sequence."""
    validate_policy(policy)
    if not reason.strip():
        raise ValueError('A policy change needs an audit reason')
    db = store.db
    db.execute('BEGIN IMMEDIATE')
    try:
        require_mutation_database(db)
        history = policy_history(db)
        current = history[-1]['policy']
        if {**current, 'small_probability': policy['small_probability']} != policy:
            raise ValueError('Only mutation size probability may change within this batch')
        if current == policy:
            db.rollback()
            return history[-1]
        sequence = json.loads(db.execute("SELECT value FROM collection_settings WHERE key='mutation_sequence'").fetchone()[0])
        if sequence <= history[-1]['start_sequence']:
            raise ValueError('No generation occurred since the previous policy boundary')
        entry = {'start_sequence': sequence, 'policy': policy, 'reason': reason, 'changed_at': time.time()}
        db.execute("INSERT OR REPLACE INTO collection_settings VALUES('mutation_policy_history',?)", (canonical([*history, entry]),))
        db.execute("UPDATE collection_settings SET value=? WHERE key='mutation_policy'", (canonical(policy),))
        db.commit()
        return entry
    except BaseException:
        db.rollback()
        raise


def initialize(store, policy):
    validate_policy(policy)
    db = store.db
    prior = db.execute("SELECT value FROM collection_settings WHERE key='mutation_policy'").fetchone()
    if prior and json.loads(prior[0]) != policy:
        raise ValueError('Use a new mutation batch for a different generation policy')
    if not prior and db.execute('SELECT 1 FROM builds LIMIT 1').fetchone():
        raise ValueError('Mutation generation requires a separate empty database')
    db.executescript('''
        CREATE TABLE IF NOT EXISTS mutation_lineage(
            build_id TEXT PRIMARY KEY,parent_id TEXT NOT NULL,parent_body TEXT NOT NULL,
            parent_targets TEXT NOT NULL,parent_origins TEXT NOT NULL,sequence INTEGER UNIQUE NOT NULL,
            seed TEXT NOT NULL,size TEXT NOT NULL,axes TEXT NOT NULL,changes TEXT NOT NULL,
            cards_changed INTEGER NOT NULL,relics_changed INTEGER NOT NULL,created REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS mutation_target_origins(
            build_id TEXT,parent_id TEXT,run_hash TEXT,origin_floor INTEGER,target_floor INTEGER,target_id TEXT,
            PRIMARY KEY(build_id,parent_id,run_hash,origin_floor,target_floor,target_id));
    ''')
    with db:
        for key, value in [('mutation_policy', policy), ('target_policy', TARGET_POLICY), ('mutation_sequence', 0)]:
            db.execute('INSERT OR IGNORE INTO collection_settings VALUES(?,?)', (key, canonical(value)))
    require_mutation_database(db)
    policy_history(db)


def multiset_distance(before, after):
    before, after = Counter(before), Counter(after)
    return max(sum((before-after).values()), sum((after-before).values()))


def relic_state(relic_id, rng):
    domains = COUNTER_DOMAINS.get(relic_id, {})
    state = {key: rng.choice(values) for key, values in sorted(domains.items())}
    if relic_id == 'WONGOS_MYSTERY_TICKET':
        state['GaveRelic'] = state['CombatsFinished'] >= 5
    validate_counter_relation(relic_id, state)
    return Relic(relic_id, tuple(sorted(state.items())))


def mutate(parent, catalog, rng, size, axes, policy):
    """Every edit touches a different original item; reject net-cancelling edits."""
    if parent.mutation != 'spire_codex_run_v1':
        raise ValueError('Only genuine real-run parents are allowed')
    card_count = rng.randint(*policy[size]['cards']) if axes in ('cards', 'both') else 0
    relic_count = rng.randint(*policy[size]['relics']) if axes in ('relics', 'both') else 0
    cards = list(enumerate(parent.cards)); relics = list(enumerate(parent.relics))
    used_cards, used_relics, changes = set(), set(), []
    # New cards come from ordinary rewards. Special source cards/enchantments
    # remain intact unless that exact card is selected for an edit.
    additions = [cid for cid in catalog.card_pool if catalog.cards[cid]['rarity'] in ORDINARY
                 and catalog.cards[cid]['pool'] in ('SILENT_CARD_POOL', 'COLORLESS_CARD_POOL')]
    normal_relics = [rid for rid in catalog.relic_pool if catalog.relics[rid]['rarity'] in ORDINARY]
    for step in range(card_count):
        eligible = [(i, c) for i, c in cards if i >= 0 and i not in used_cards]
        operations = ['add'] if len(cards) < catalog.config['max_deck_size'] else []
        if eligible:
            operations += ['replace']
            if len(cards) > 1: operations += ['remove']
            if any(c.upgrade < catalog.cards[c.id]['max_upgrade_level'] for _, c in eligible): operations += ['upgrade']
        if not operations: return None
        op = rng.choice(operations)
        before, index = None, None
        if op != 'add':
            options = [(i, c) for i, c in eligible if op != 'upgrade' or c.upgrade < catalog.cards[c.id]['max_upgrade_level']]
            index, before = rng.choice(options); used_cards.add(index)
            cards = [(i, c) for i, c in cards if i != index]
        after = None
        if op == 'upgrade': after = replace(before, upgrade=before.upgrade+1)
        elif op in ('add', 'replace'):
            allowed = [cid for cid in additions if catalog.cards[cid]['pool'] != 'COLORLESS_CARD_POOL'
                       or catalog.colorless_count([c for _, c in cards]) < catalog.config['max_colorless']]
            if not allowed: return None
            cid = rng.choice(allowed)
            after = Card(cid, rng.choice([0, 1]) if catalog.cards[cid]['max_upgrade_level'] >= 1 else 0)
        if after is not None: cards.append((-(step+1), after))
        changes.append({'kind': 'card', 'operation': op, 'index': index,
                        'before': before.to_dict() if before else None, 'after': after.to_dict() if after else None})
    protected = {h[2] for h in parent.ancient_history} | {'RING_OF_THE_SNAKE', 'RING_OF_THE_DRAKE'}
    protected |= {r.id for r in parent.relics if catalog.relics[r.id]['rarity'] not in ORDINARY}
    for step in range(relic_count):
        eligible = [(i, r) for i, r in relics if i >= 0 and i not in used_relics and r.id not in protected]
        present = {r.id for _, r in relics}
        # Never re-add a removed ID: that would cancel an edit or move its order.
        allowed = [rid for rid in normal_relics if rid not in present and rid not in {r.id for r in parent.relics}]
        operations = ['add'] if allowed else []
        if eligible:
            operations += ['remove']
            if allowed: operations += ['replace']
        if not operations: return None
        op = rng.choice(operations); before, index = None, None
        if op != 'add':
            index, before = rng.choice(eligible); used_relics.add(index)
            relics = [(i, r) for i, r in relics if i != index]
        after = relic_state(rng.choice(allowed), rng) if op != 'remove' else None
        if after is not None: relics.append((-(step+1), after))
        changes.append({'kind': 'relic', 'operation': op, 'index': index,
                        'before': asdict(before) if before else None, 'after': asdict(after) if after else None})
    child = replace(parent, cards=tuple(c for _, c in cards), relics=tuple(r for _, r in relics),
                    parent=parent.id, generation=1, mutation=MUTATION)
    if (multiset_distance(parent.cards, child.cards) != card_count
            or multiset_distance(parent.relics, child.relics) != relic_count): return None
    catalog.validate(child)
    return child, changes, card_count, relic_count


def validate_lineage(db, build_id, catalog=None):
    row = db.execute('SELECT * FROM mutation_lineage WHERE build_id=?', (build_id,)).fetchone()
    if row is None: raise ValueError('Mutation provenance is missing')
    child = Build.from_dict(json.loads(db.execute('SELECT body FROM builds WHERE id=?', (build_id,)).fetchone()[0]))
    parent = Build.from_dict(json.loads(row['parent_body']))
    history = policy_history(db)
    policy = next(entry['policy'] for entry in reversed(history) if entry['start_sequence'] <= row['sequence'])
    if row['size'] not in ('small', 'large') or row['axes'] not in policy['axes_weights']:
        raise ValueError('Unknown mutation size or axes')
    for kind, count in [('cards', row['cards_changed']), ('relics', row['relics_changed'])]:
        enabled = row['axes'] in (kind, 'both')
        low, high = policy[row['size']][kind]
        if (enabled and not low <= count <= high) or (not enabled and count != 0):
            raise ValueError('Mutation edit count outside approved range')
    if (child.id != build_id or parent.id != row['parent_id'] or child.parent != parent.id
            or child.mutation != MUTATION or parent.mutation != 'spire_codex_run_v1'
            or child.generation != 1 or child.family != parent.family
            or (child.act_id, child.act, child.ancient_history) != (parent.act_id, parent.act, parent.ancient_history)):
        raise ValueError('Mutation parent, generation or act was changed')
    if (multiset_distance(parent.cards, child.cards) != row['cards_changed']
            or multiset_distance(parent.relics, child.relics) != row['relics_changed']):
        raise ValueError('Mutation edit audit differs from actual input')
    changes = json.loads(row['changes'])
    cards, relics = list(enumerate(parent.cards)), list(enumerate(parent.relics))
    seen = {'card': set(), 'relic': set()}
    if Counter(c['kind'] for c in changes) != Counter({'card': row['cards_changed'], 'relic': row['relics_changed']}):
        raise ValueError('Mutation change log length differs')
    for n, change in enumerate(changes):
        kind, op, index = change['kind'], change['operation'], change['index']
        if op not in ('add', 'remove', 'replace', 'upgrade') or (kind == 'relic' and op == 'upgrade'):
            raise ValueError('Invalid mutation operation')
        items = cards if kind == 'card' else relics
        encode = (lambda x: x.to_dict()) if kind == 'card' else asdict
        if op == 'add':
            if index is not None or change['before'] is not None: raise ValueError('Invalid addition audit')
        else:
            match = [item for i, item in items if i == index and i >= 0]
            if len(match) != 1 or index in seen[kind] or canonical(encode(match[0])) != canonical(change['before']):
                raise ValueError('Mutation changes do not match the parent')
            seen[kind].add(index)
            items[:] = [(i, item) for i, item in items if i != index]
        if change['after'] is not None:
            value = change['after']
            item = Card(**value) if kind == 'card' else Relic(value['id'], tuple(tuple(x) for x in value['state']))
            items.append((-(n+1), item))
        elif op != 'remove': raise ValueError('Mutation operation lost its result')
    if tuple(c for _, c in cards) != child.cards or tuple(r for _, r in relics) != child.relics:
        raise ValueError('Mutation replay differs from stored child')
    locked = {h[2] for h in parent.ancient_history} | {'RING_OF_THE_SNAKE', 'RING_OF_THE_DRAKE'}
    if catalog is not None:
        locked |= {r.id for r in parent.relics if catalog.relics[r.id]['rarity'] not in ORDINARY}
        catalog.validate(child)
    if [r for r in parent.relics if r.id in locked] != [r for r in child.relics if r.id in locked]:
        raise ValueError('Protected relic identity, order or counters changed')
    expected = set(json.loads(row['parent_targets']))
    actual = {r[0] for r in db.execute('SELECT DISTINCT target_id FROM mutation_target_origins WHERE build_id=?', (build_id,))}
    if expected != actual or not expected: raise ValueError('Mutation target provenance differs')
    origins = json.loads(row['parent_origins'])
    recorded = {(r['run_hash'], r['origin_floor'], r['target_floor'], r['target_id']) for r in origins}
    inherited = {tuple(r) for r in db.execute('SELECT run_hash,origin_floor,target_floor,target_id FROM mutation_target_origins WHERE build_id=? AND parent_id=?', (build_id, parent.id))}
    if (recorded != inherited or any(r['build_id'] != parent.id or abs(r['origin_floor']-r['target_floor']) > 2 for r in origins)
            or {r['target_id'] for r in origins} != expected):
        raise ValueError('Mutation target origins differ from the recorded parent window')
    if any(json.loads(r[0])['id'] not in expected for r in db.execute('SELECT target FROM jobs WHERE build_id=?', (build_id,))):
        raise ValueError('Mutation job escaped its parent target window')
    return row


class Generator:
    def __init__(self, source, destination, catalog, teacher, policy):
        self.source, self.destination = source, destination
        self.catalog, self.teacher, self.policy = catalog, teacher, policy
        initialize(destination, policy)
        self.groups, self.refreshed = {}, 0
        if {r[0] for r in destination.db.execute('SELECT DISTINCT teacher FROM jobs')} - {canonical(teacher)}:
            raise ValueError('Mutation teacher differs from the real-run teacher')

    def refresh(self):
        from .run_import import source_groups
        families = source_groups(self.source.db)
        groups = {act: defaultdict(list) for act in self.policy['map_weights']}
        db = self.source.db
        rows = db.execute("""SELECT * FROM builds WHERE id IN (
            SELECT build_id FROM jobs WHERE status='complete'
            UNION SELECT build_id FROM prior_collected_inputs WHERE source_status='complete')""").fetchall()
        target_origins = defaultdict(list)
        for r in db.execute('SELECT * FROM target_origins ORDER BY build_id,run_hash,origin_floor,target_floor,target_id'):
            target_origins[r['build_id']].append(dict(r))
        for row in rows:
            parent = Build.from_dict(json.loads(row['body']))
            if parent.act_id not in groups or parent.mutation != 'spire_codex_run_v1': continue
            self.catalog.validate(parent)
            if parent.id not in target_origins: continue
            parent = replace(parent, family=families.get(parent.id, parent.family))
            # Equal weight per card composition avoids over-weighting repeated
            # snapshots that only differ by upgrades, relics or floor.
            key = tuple(sorted(Counter(c.id for c in parent.cards).items()))
            groups[parent.act_id][key].append((parent, target_origins[parent.id]))
        if not all(groups.values()): raise ValueError('Both requested maps need verified real parents')
        self.groups = {act: [items for _, items in sorted(values.items())] for act, values in groups.items()}
        self.refreshed = time.time()

    def refill(self, limit=None):
        if not self.groups or time.time()-self.refreshed >= self.policy['parent_refresh_seconds']: self.refresh()
        db = self.destination.db
        count = limit if limit is not None else self.policy['refill_builds']
        added, scheduled, attempts = 0, 0, 0
        while added < count and attempts < count*100:
            attempts += 1
            sequence = json.loads(db.execute("SELECT value FROM collection_settings WHERE key='mutation_sequence'").fetchone()[0])
            seed = digest([MUTATION, self.policy['seed'], sequence]); rng = random.Random(seed)
            act = rng.choices(list(self.policy['map_weights']), list(self.policy['map_weights'].values()))[0]
            parent, origins = rng.choice(rng.choice(self.groups[act]))
            size = 'small' if rng.random() < self.policy['small_probability'] else 'large'
            axes = rng.choices(list(self.policy['axes_weights']), list(self.policy['axes_weights'].values()))[0]
            # Retry within the chosen map/size/axes so rejected net-cancelling
            # edits do not silently bias the configured map and size ratios.
            candidate = None
            for _ in range(100):
                attempt = mutate(parent, self.catalog, rng, size, axes, self.policy)
                if attempt is None: continue
                bid = attempt[0].id
                if (self.source.db.execute('SELECT 1 FROM builds WHERE id=?', (bid,)).fetchone()
                        or db.execute('SELECT 1 FROM builds WHERE id=?', (bid,)).fetchone()): continue
                candidate = attempt
                break
            db.execute('BEGIN IMMEDIATE')
            try:
                current = json.loads(db.execute("SELECT value FROM collection_settings WHERE key='mutation_sequence'").fetchone()[0])
                if current != sequence: raise ValueError('Concurrent mutation generator')
                active_policy = json.loads(db.execute("SELECT value FROM collection_settings WHERE key='mutation_policy'").fetchone()[0])
                if active_policy != self.policy: raise ValueError('Mutation generator policy changed; restart the controller')
                db.execute("UPDATE collection_settings SET value=? WHERE key='mutation_sequence'", (canonical(sequence+1),))
                if candidate:
                    child, changes, nc, nr = candidate
                    if not db.execute('SELECT 1 FROM builds WHERE id=?', (child.id,)).fetchone():
                        targets = sorted({r['target_id'] for r in origins})
                        allowed = {t['id']: t for t in self.catalog.targets(child)}
                        if not set(targets) <= allowed.keys(): raise ValueError('Parent target crosses acts')
                        db.execute('INSERT INTO builds VALUES(?,?,?,?)', (child.id, child.family, child.split, canonical(child.to_dict())))
                        db.execute('INSERT INTO mutation_lineage VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',
                            (child.id, parent.id, canonical(parent.to_dict()), canonical(targets), canonical(origins),
                             sequence, seed, size, axes, canonical(changes), nc, nr, time.time()))
                        db.executemany('INSERT INTO mutation_target_origins VALUES(?,?,?,?,?,?)',
                            [(child.id, parent.id, r['run_hash'], r['origin_floor'], r['target_floor'], r['target_id']) for r in origins])
                        for tid in targets:
                            for j in range(self.catalog.config['initial_seeds_per_pair']):
                                battle_seed = digest(['battle', self.catalog.config['battle_seed'], j])[:16]
                                jid = digest([child.id, tid, battle_seed, self.teacher])
                                db.execute('INSERT INTO jobs(id,build_id,target,seed,teacher,created) VALUES(?,?,?,?,?,?)',
                                    (jid, child.id, canonical(allowed[tid]), battle_seed, canonical(self.teacher), time.time()))
                                scheduled += 1
                        validate_lineage(db, child.id, self.catalog)
                        added += 1
                db.commit()
            except BaseException:
                db.rollback(); raise
        if added != count: raise ValueError('Insufficient unique legal neighbours within generation bound')
        return {'builds_added': added, 'jobs_added': scheduled, 'attempted_candidates': attempts,
                'counts': self.destination.counts()}
