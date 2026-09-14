"""Synthetic parent rows exercise mutation bounds, provenance and priority routing."""
from collections import Counter
from dataclasses import replace
import json
from pathlib import Path
import random
import sqlite3

import pytest

from damage_model.catalog import Catalog
from damage_model.mutations import Generator, MUTATION, change_size_probability, initialize, mutate, multiset_distance, policy_history, relic_state, validate_lineage
from damage_model.priority_store import PriorityStore
from damage_model.schema import Build, Card, Relic, canonical, digest
from damage_model.store import Store
from damage_model.worker import request_for

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def catalog():
    return Catalog.load(ROOT/'catalogs/game-0.111.0.raw.json', ROOT/'configs/real-runs-8s.json')


@pytest.fixture
def policy():
    return json.loads((ROOT/'configs/mutations-8s.json').read_text())


def parent_for(catalog, act_id):
    history = [(1, 'NEOW', 'BOOMING_CONCH'), (2, 'OROBAS', 'DRIFTWOOD')]
    if act_id == 'GLORY': history.append((3, 'NONUPEIPE', 'BLESSED_ANTLER'))
    relics = [Relic('RING_OF_THE_SNAKE'), *[relic_state(r, random.Random(1)) for _, _, r in history],
              Relic('PEN_NIB', (('AttacksPlayed', 9),)), Relic('HAPPY_FLOWER', (('TurnsSeen', 2),))]
    cards = [Card(c) for c in catalog.raw['character']['starting_deck']]
    cards += [Card('BACKFLIP', 1), Card('DAGGER_THROW'), Card('APOTHEOSIS')]
    build = Build(act_id, catalog.acts[act_id]['act'], tuple(cards), tuple(relics), tuple(history),
                  'synthetic-'+act_id, mutation='spire_codex_run_v1')
    catalog.validate(build)
    return build


@pytest.fixture
def databases(tmp_path, catalog, policy):
    real, mutations = Store(tmp_path/'real.sqlite'), Store(tmp_path/'mutations.sqlite')
    for act_id in ('HIVE', 'GLORY'):
        parent = parent_for(catalog, act_id)
        target = catalog.targets(parent)[0]
        real.schedule(parent, [target], ['fixture'], {'fixture': True})
        # Deliberately synthetic completion, never a native training artifact.
        real.db.execute("UPDATE jobs SET status='complete'")
        real.db.execute('INSERT INTO target_origins VALUES(?,?,?,?,?)', (parent.id, 'test-run-'+act_id, 25, 26, target['id']))
        real.db.commit()
    yield real, mutations
    real.db.close(); mutations.db.close()


def test_refill_released_lock_matches_uncontended_generation(databases, tmp_path, catalog, policy, monkeypatch):
    real, destination = databases
    baseline = Store(tmp_path/'uncontended.sqlite')
    generator = Generator(real, destination, catalog, {'fixture': True}, policy)
    reference = Generator(real, baseline, catalog, {'fixture': True}, policy)
    monkeypatch.setattr('damage_model.mutations.time.time', lambda: 12345678.0)
    reference.refill(5)
    original_source = list(real.db.iterdump())
    destination.db.execute('PRAGMA busy_timeout=0')
    holder = sqlite3.connect(tmp_path/'mutations.sqlite')
    holder.execute('BEGIN IMMEDIATE')
    waits = []

    def release(delay):
        waits.append(delay)
        assert not destination.db.in_transaction
        assert destination.db.execute('SELECT count(*) FROM builds').fetchone()[0] == 0
        holder.rollback()

    monkeypatch.setattr('damage_model.store.time.sleep', release)
    try:
        generator.refill(5)
        assert waits == [0.25]
        # Includes exact builds, counters, card state, lineage, seeds and job IDs.
        assert list(destination.db.iterdump()) == list(baseline.db.iterdump())
        assert list(real.db.iterdump()) == original_source
        assert destination.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
    finally:
        holder.close()
        baseline.db.close()


def test_refill_persistent_busy_preserves_sequence_and_all_rows(databases, tmp_path, catalog, policy, monkeypatch):
    real, destination = databases
    generator = Generator(real, destination, catalog, {'fixture': True}, policy)
    destination.db.execute('PRAGMA busy_timeout=0')
    before = list(destination.db.iterdump())
    holder = sqlite3.connect(tmp_path/'mutations.sqlite')
    holder.execute('BEGIN IMMEDIATE')
    delays, trace = [], []
    destination.db.set_trace_callback(trace.append)
    monkeypatch.setattr('damage_model.store.time.sleep', delays.append)
    try:
        with pytest.raises(sqlite3.OperationalError) as error:
            generator.refill(1)
        assert error.value.sqlite_errorcode == sqlite3.SQLITE_BUSY
        assert trace.count('BEGIN IMMEDIATE') == 3
        assert delays == [0.25, 0.5]
        assert not destination.db.in_transaction
        assert list(destination.db.iterdump()) == before
    finally:
        holder.rollback()
        holder.close()


@pytest.mark.parametrize('changed', ['sequence', 'policy'])
def test_refill_rechecks_generation_state_after_lock_wait(databases, tmp_path, catalog, policy, monkeypatch, changed):
    real, destination = databases
    generator = Generator(real, destination, catalog, {'fixture': True}, policy)
    destination.db.execute('PRAGMA busy_timeout=0')
    holder = sqlite3.connect(tmp_path/'mutations.sqlite')
    holder.execute('BEGIN IMMEDIATE')
    if changed == 'sequence':
        holder.execute("UPDATE collection_settings SET value='1' WHERE key='mutation_sequence'")
    else:
        holder.execute("UPDATE collection_settings SET value=? WHERE key='mutation_policy'",
                       (canonical({**policy, 'small_probability': 0.5}),))
    monkeypatch.setattr('damage_model.store.time.sleep', lambda _: holder.commit())
    try:
        with pytest.raises(ValueError, match='Concurrent mutation generator|policy changed'):
            generator.refill(1)
        assert destination.db.execute('SELECT count(*) FROM builds').fetchone()[0] == 0
        assert destination.db.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
        assert not destination.db.in_transaction
    finally:
        holder.close()


def test_refill_body_failure_rolls_back_without_replay(databases, catalog, policy, monkeypatch):
    real, destination = databases
    generator = Generator(real, destination, catalog, {'fixture': True}, policy)
    destination.db.execute("CREATE TRIGGER fail_lineage BEFORE INSERT ON mutation_lineage BEGIN SELECT RAISE(ABORT,'synthetic lineage failure'); END")
    before, trace = list(destination.db.iterdump()), []
    destination.db.set_trace_callback(trace.append)
    monkeypatch.setattr('damage_model.store.time.sleep', lambda _: pytest.fail('Transaction body was retried'))
    with pytest.raises(sqlite3.IntegrityError, match='synthetic lineage failure'):
        generator.refill(1)
    assert trace.count('BEGIN IMMEDIATE') == 1
    assert list(destination.db.iterdump()) == before
    assert not destination.db.in_transaction


def test_refill_commit_error_is_not_replayed(databases, catalog, policy, monkeypatch):
    real, destination = databases
    generator = Generator(real, destination, catalog, {'fixture': True}, policy)
    connection = destination.db
    before, commits = list(connection.iterdump()), []

    class CommitFailure:
        def __getattr__(self, name):
            return getattr(connection, name)

        def commit(self):
            commits.append(True)
            error = sqlite3.OperationalError('synthetic commit busy')
            error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise error

    destination.db = CommitFailure()
    monkeypatch.setattr('damage_model.store.time.sleep', lambda _: pytest.fail('Commit was retried'))
    try:
        with pytest.raises(sqlite3.OperationalError, match='synthetic commit busy'):
            generator.refill(1)
        assert commits == [True]
        assert list(connection.iterdump()) == before
        assert not connection.in_transaction
    finally:
        destination.db = connection


def test_historical_completed_parents_remain_eligible(databases, catalog, policy):
    real, destination = databases
    for row in real.db.execute('SELECT * FROM jobs').fetchall():
        real.db.execute('INSERT INTO prior_collected_inputs VALUES(?,?,?,?,?,?,?,?)',
                        (row['build_id'], json.loads(row['target'])['id'], row['seed'], 'frozen.sqlite',
                         row['id'], 'complete', row['teacher'], 'fixture'))
    real.db.execute('DELETE FROM jobs'); real.db.commit()
    generator = Generator(real, destination, catalog, {'fixture': True}, policy)
    generator.refresh()
    assert all(generator.groups[act] for act in ('HIVE', 'GLORY'))


def test_relic_mutation_preserves_saved_card_state(catalog, policy):
    card = Card('MAD_SCIENCE', 1, persistent_state={'TinkerTimeType': 2, 'TinkerTimeRider': 5})
    parent = parent_for(catalog, 'HIVE')
    parent = replace(parent, cards=(*parent.cards, card))
    children = [mutate(parent, catalog, random.Random(seed), 'small', 'relics', policy) for seed in range(8)]
    assert any(children)
    for result in filter(None, children):
        child = Build.from_dict(result[0].to_dict())
        assert child.cards == parent.cards and card in child.cards


@pytest.mark.parametrize('act_id', ['HIVE', 'GLORY'])
@pytest.mark.parametrize('size', ['small', 'large'])
@pytest.mark.parametrize('axes', ['cards', 'relics', 'both'])
def test_exact_edit_bounds_and_protected_items(catalog, policy, act_id, size, axes):
    parent = parent_for(catalog, act_id)
    seen = 0
    for seed in range(80):
        result = mutate(parent, catalog, random.Random(seed), size, axes, policy)
        if result is None: continue
        child, changes, nc, nr = result; seen += 1
        catalog.validate(child)
        assert child.ancient_history == parent.ancient_history and child.act_id == act_id
        assert child.family == parent.family and child.split == parent.split and child.generation == 1
        assert multiset_distance(parent.cards, child.cards) == nc
        assert multiset_distance(parent.relics, child.relics) == nr
        assert len(changes) == nc+nr
        assert 1 <= len(child.cards) <= 45 and catalog.colorless_count(child.cards) <= 5
        assert nc == 0 if axes == 'relics' else policy[size]['cards'][0] <= nc <= policy[size]['cards'][1]
        assert nr == 0 if axes == 'cards' else policy[size]['relics'][0] <= nr <= policy[size]['relics'][1]
        locked = {h[2] for h in parent.ancient_history} | {'RING_OF_THE_SNAKE'}
        assert [r for r in child.relics if r.id in locked] == [r for r in parent.relics if r.id in locked]
    # Rejection is expected when additions/removals cancel in the multiset.
    assert seen > 20


def test_full_deck_and_colorless_limit(catalog, policy):
    parent = parent_for(catalog, 'GLORY')
    parent = replace(parent, cards=tuple([Card('APOTHEOSIS')]*5+[Card('BACKFLIP')]*40))
    for seed in range(60):
        result = mutate(parent, catalog, random.Random(seed), 'large', 'both', policy)
        if result is not None: catalog.validate(result[0])


def test_source_unchanged_resume_dedup_and_window(databases, catalog, policy):
    real, derived = databases
    before = list(real.db.iterdump())
    g = Generator(real, derived, catalog, {'fixture': True}, policy)
    first = g.refill(45)
    initial = {r[0] for r in derived.db.execute('SELECT id FROM builds')}
    Generator(real, derived, catalog, {'fixture': True}, policy).refill(15)
    assert list(real.db.iterdump()) == before
    assert derived.db.execute('SELECT count(*) FROM builds').fetchone()[0] == 60
    assert first['jobs_added'] == 45*4
    for row in derived.db.execute('SELECT * FROM builds'):
        lineage = validate_lineage(derived.db, row['id'], catalog)
        child = Build.from_dict(json.loads(row['body']))
        assert child.id != lineage['parent_id']
        jobs = list(derived.db.execute('SELECT target,seed FROM jobs WHERE build_id=?', (child.id,)))
        expected = set(json.loads(lineage['parent_targets']))
        assert {json.loads(r['target'])['id'] for r in jobs} == expected
        assert len(jobs) == len(expected)*4
    assert initial <= {r[0] for r in derived.db.execute('SELECT id FROM builds')}
    assert derived.db.execute('SELECT count(*) FROM target_origins').fetchone()[0] == 0
    assert not derived.db.execute("SELECT 1 FROM sqlite_master WHERE name='source_runs'").fetchone()


@pytest.mark.parametrize('small_probability', [.8, .6])
def test_reproducible_generation_and_distribution(databases, tmp_path, catalog, policy, small_probability):
    policy = {**policy, 'small_probability': small_probability}
    real, first = databases
    second = Store(tmp_path/'second.sqlite')
    try:
        Generator(real, first, catalog, {'fixture': True}, policy).refill(250)
        Generator(real, second, catalog, {'fixture': True}, policy).refill(250)
        assert [tuple(r) for r in first.db.execute('SELECT id,body FROM builds ORDER BY id')] == [tuple(r) for r in second.db.execute('SELECT id,body FROM builds ORDER BY id')]
        acts = Counter(json.loads(r[0])['act_id'] for r in first.db.execute('SELECT body FROM builds'))
        sizes = dict(first.db.execute('SELECT size,count(*) FROM mutation_lineage GROUP BY size'))
        assert 120 < acts['GLORY'] < 185
        assert abs(sizes['small']-250*small_probability) < 35
        assert set(r[0] for r in first.db.execute('SELECT axes FROM mutation_lineage')) == {'cards', 'relics', 'both'}
    finally: second.db.close()


def test_priority_returns_to_new_real_work_and_keeps_writes_separate(databases, catalog, policy):
    real, derived = databases
    Generator(real, derived, catalog, {'fixture': True}, policy).refill(2)
    queue = PriorityStore(real, derived, {'fixture': True})
    first = queue.claim(); assert first['collection_dataset'] == 'mutation'
    parent = parent_for(catalog, 'HIVE')
    real.schedule(parent, catalog.targets(parent)[:1], ['new-real'], {'fixture': True})
    second = queue.claim(); assert second['collection_dataset'] == 'real' and second['seed'] == 'new-real'
    queue.finish(first, {'status': 'Failed', 'error': 'synthetic test'})
    assert derived.counts()['failed'] == 1 and real.counts().get('failed', 0) == 0
    assert queue.claim() is None  # Never conceal a real validation failure behind the other queue.


def test_mutation_request_retains_teacher_and_skips_pickup(databases, catalog, policy):
    real, derived = databases
    Generator(real, derived, catalog, {'fixture': True}, policy).refill(1)
    job = derived.claim()
    request = request_for(job, catalog.config)
    assert all(r['addWithoutObtainedEffects'] for r in request['relics'])
    assert request['shortSearchBudgetOverrideMilliseconds'] == 8000
    assert request['searchMaxDegreeOfParallelismForTest'] == 1
    assert request['timeoutSeconds'] == 120 and request['potions'] == []
    assert request['ascension'] == 10


@pytest.mark.parametrize('corrupt', ['count', 'target', 'parent', 'change'])
def test_corrupt_lineage_refused(databases, catalog, policy, corrupt):
    real, derived = databases
    Generator(real, derived, catalog, {'fixture': True}, policy).refill(1)
    bid = derived.db.execute('SELECT id FROM builds').fetchone()[0]
    if corrupt == 'count': derived.db.execute('UPDATE mutation_lineage SET cards_changed=7')
    elif corrupt == 'target': derived.db.execute("UPDATE mutation_target_origins SET target_id='NOT_IN_PARENT'")
    elif corrupt == 'parent': derived.db.execute("UPDATE mutation_lineage SET parent_id='wrong'")
    else: derived.db.execute("UPDATE mutation_lineage SET changes='[]'")
    with pytest.raises(ValueError): validate_lineage(derived.db, bid, catalog)


def test_reject_new_policy_or_non_real_parent(databases, catalog, policy):
    real, derived = databases
    initialize(derived, policy)
    with pytest.raises(ValueError): initialize(derived, {**policy, 'seed': 2})
    with pytest.raises(ValueError): initialize(real, policy)
    with pytest.raises(ValueError): mutate(replace(parent_for(catalog, 'HIVE'), mutation=MUTATION), catalog, random.Random(1), 'small', 'both', policy)


def test_size_ratio_switch_preserves_rows_and_rejects_stale_generator(databases, catalog, policy):
    real, derived = databases
    old_policy = {**policy, 'small_probability': .8}
    old_generator = Generator(real, derived, catalog, {'fixture': True}, old_policy)
    old_generator.refill(12)
    tables = ('builds', 'jobs', 'attempts', 'job_quarantines', 'mutation_lineage', 'mutation_target_origins')
    before = {t: [tuple(r) for r in derived.db.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in tables}
    boundary = json.loads(derived.db.execute("SELECT value FROM collection_settings WHERE key='mutation_sequence'").fetchone()[0])
    entry = change_size_probability(derived, policy, 'User requested 60/40 for future builds')
    assert entry['start_sequence'] == boundary
    assert entry['policy']['small_probability'] == .6
    assert policy_history(derived.db)[0]['policy'] == old_policy
    assert before == {t: [tuple(r) for r in derived.db.execute(f'SELECT * FROM {t} ORDER BY 1')] for t in tables}
    for row in before['builds']: validate_lineage(derived.db, row[0], catalog)
    assert change_size_probability(derived, policy, 'Idempotent resume') == entry
    with pytest.raises(ValueError, match='policy changed'):
        old_generator.refill(1)
    assert json.loads(derived.db.execute("SELECT value FROM collection_settings WHERE key='mutation_sequence'").fetchone()[0]) == boundary
    Generator(real, derived, catalog, {'fixture': True}, policy).refill(20)
    assert derived.db.execute('SELECT count(*) FROM mutation_lineage WHERE sequence>=?', (boundary,)).fetchone()[0] == 20
    for row in derived.db.execute('SELECT id FROM builds'): validate_lineage(derived.db, row[0], catalog)


@pytest.mark.parametrize('change', [{'seed': 2}, {'small_probability': .5}, {'large': {'cards': [1, 9], 'relics': [1, 4]}}])
def test_size_ratio_switch_refuses_other_changes(databases, catalog, policy, change):
    real, derived = databases
    Generator(real, derived, catalog, {'fixture': True}, policy).refill(2)
    before = list(derived.db.iterdump())
    with pytest.raises(ValueError):
        change_size_probability(derived, {**policy, **change}, 'Invalid fixture change')
    assert list(derived.db.iterdump()) == before
