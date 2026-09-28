"""Synthetic migration fixtures preserve actual schema, policies and lineage."""
import json
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from prepare_standalone_handoff import migrate_queue
from damage_model.catalog import Catalog
from damage_model.mutations import Generator, validate_lineage
from damage_model.provenance import teacher_for
from damage_model.schema import canonical
from damage_model.store import Store
from test_mutations import parent_for


@pytest.fixture
def setup(tmp_path):
    catalog = Catalog.load(ROOT / 'catalogs/game-0.111.0.raw.json', ROOT / 'configs/real-runs-8s.json')
    teacher = {**teacher_for(catalog, ROOT / 'configs/teacher.json'), 'collector_source': 'unit-native',
               'collector_sha256': 'a' * 64}
    candidate = {**teacher, 'collector_source': 'unit-accepted', 'collector_sha256': 'b' * 64,
                 'execution_backend': 'standalone-managed-native', 'validation_scope': 'isolated-experiment',
                 'standalone_host_sha256': 'c' * 64, 'standalone_unlock_state': 'progress-snapshot',
                 'progress_snapshot_sha256': 'd' * 64}
    source = tmp_path / 'native.sqlite'; store = Store(source)
    parent = parent_for(catalog, 'HIVE'); targets = catalog.targets(parent)[:2]
    for target in targets:
        store.schedule(parent, [target], catalog.battle_seeds(parent.act_id, target['id'])[:4], teacher)
        store.db.execute('INSERT INTO target_origins VALUES(?,?,?,?,?)', (parent.id, 'unit-run', 25, 26, target['id']))
        store.db.commit()
    with store.db:
        store.db.execute("INSERT INTO collection_settings VALUES('target_policy',?)",
                         (canonical({'name': 'source_floor_window_v1', 'radius': 2, 'same_act': True}),))
        store.db.execute('CREATE TABLE source_runs(hash TEXT PRIMARY KEY,body TEXT)')
        store.db.execute("INSERT INTO source_runs VALUES('unit-run','verbatim source body')")
        jobs = list(store.db.execute('SELECT id FROM jobs ORDER BY created,id'))
        for row, status in zip(jobs, ['pending', 'complete', 'failed', 'quarantined', 'excluded_target', 'pending', 'pending', 'pending']):
            store.db.execute('UPDATE jobs SET status=?,result=? WHERE id=?', (status, canonical({'originalStatus': status}), row['id']))
        store.db.execute('UPDATE jobs SET attempts=2 WHERE id=?', (jobs[0]['id'],))
        for i in range(2):
            store.db.execute('INSERT INTO attempts(job_id,lease,status,result,finished) VALUES(?,?,?,?,?)',
                             (jobs[0]['id'], f'old-{i}', 'retry', canonical({'failure': i}), float(i)))
    store.db.close()
    return source, catalog, teacher, candidate, parent, targets


def dump(path):
    with sqlite3.connect(path) as db: return list(db.iterdump())


def test_only_pending_jobs_move_and_old_outcomes_cannot_be_rescheduled(setup, tmp_path):
    source, catalog, previous, teacher, parent, targets = setup
    before = dump(source); destination = tmp_path / 'standalone.sqlite'
    report = migrate_queue(source, destination, teacher, catalog, {'unitAcceptance': True})
    assert report['pendingMigrated'] == 4 and report['completedResultsRelabelled'] == 0
    assert dump(source) == before
    store = Store(destination)
    assert store.counts() == {'pending': 4}
    assert store.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
    assert store.db.execute('SELECT count(*) FROM jobs WHERE attempts!=0 OR lease IS NOT NULL OR result IS NOT NULL').fetchone()[0] == 0
    assert {r[0] for r in store.db.execute('SELECT teacher FROM jobs')} == {canonical(teacher)}
    assert store.db.execute('SELECT max(source_attempts) FROM standalone_batch_origins').fetchone()[0] == 2
    assert store.db.execute('SELECT body FROM source_runs').fetchone()[0] == 'verbatim source body'
    assert store.db.execute('SELECT count(*) FROM prior_collected_inputs').fetchone()[0] == 3
    with sqlite3.connect(source) as old:
        for target, seed in old.execute("SELECT target,seed FROM jobs WHERE status IN ('complete','failed','quarantined','pending')"):
            assert store.schedule(parent, [json.loads(target)], [seed], teacher) == 0
    store.db.close()


@pytest.mark.parametrize('change', ['running', 'leased_pending', 'budget', 'dop', 'game', 'wrong_target',
                                   'wrong_seed', 'missing_origin', 'wrong_job_id', 'mixed_teachers'])
def test_policy_drift_and_active_or_untraceable_inputs_are_rejected(setup, tmp_path, change):
    source, catalog, previous, candidate, parent, targets = setup
    if change == 'budget': candidate['search_ms'] = 16000
    elif change == 'dop': candidate['dop'] = 2
    elif change == 'game': candidate['game_sha256'] = 'other'
    else:
        with sqlite3.connect(source) as db:
            jid = db.execute("SELECT id FROM jobs WHERE status='pending' LIMIT 1").fetchone()[0]
            if change == 'running': db.execute("UPDATE jobs SET status='running' WHERE id=?", (jid,))
            elif change == 'leased_pending': db.execute("UPDATE jobs SET lease='still-owned' WHERE id=?", (jid,))
            elif change == 'wrong_target': db.execute('UPDATE jobs SET target=? WHERE id=?', (canonical({'id': 'UNKNOWN'}), jid))
            elif change == 'wrong_seed': db.execute("UPDATE jobs SET seed='unapproved' WHERE id=?", (jid,))
            elif change == 'missing_origin': db.execute('DELETE FROM target_origins')
            elif change == 'wrong_job_id': db.execute("UPDATE jobs SET id='forged' WHERE id=?", (jid,))
            elif change == 'mixed_teachers': db.execute('UPDATE jobs SET teacher=? WHERE id=?', (canonical(candidate), jid))
    before = dump(source)
    with pytest.raises(ValueError):
        migrate_queue(source, tmp_path / 'rejected.sqlite', candidate, catalog, {'unitAcceptance': True})
    assert dump(source) == before
    assert not (tmp_path / 'rejected.sqlite').exists()


def test_interrupted_preparation_is_preserved_not_overwritten(setup, tmp_path):
    source, catalog, _, teacher, _, _ = setup
    temporary = tmp_path / 'standalone.preparing.sqlite'; temporary.write_bytes(b'prior failure evidence')
    with pytest.raises(ValueError, match='interrupted preparation'):
        migrate_queue(source, tmp_path / 'standalone.sqlite', teacher, catalog, {'unitAcceptance': True})
    assert temporary.read_bytes() == b'prior failure evidence'


def test_generated_mutation_lineage_and_sequence_survive_handoff(setup, tmp_path):
    source, catalog, previous, teacher, _, _ = setup
    real = Store(source); mutations_path = tmp_path / 'native-mutations.sqlite'; mutations = Store(mutations_path)
    parent = parent_for(catalog, 'GLORY'); target = catalog.targets(parent)[0]
    real.schedule(parent, [target], catalog.battle_seeds(parent.act_id, target['id'])[:1], previous)
    with real.db:
        real.db.execute("UPDATE jobs SET status='complete' WHERE build_id=?", (parent.id,))
        real.db.execute('INSERT INTO target_origins VALUES(?,?,?,?,?)',
                        (parent.id, 'unit-glory-run', 42, 43, target['id']))
    policy = json.loads((ROOT / 'configs/mutations-8s.json').read_text())
    Generator(real, mutations, catalog, previous, policy).refill(3)
    prior_lineage = [tuple(r) for r in mutations.db.execute('SELECT * FROM mutation_lineage ORDER BY build_id')]
    prior_settings = dict(mutations.db.execute('SELECT key,value FROM collection_settings'))
    mutations.db.close(); real.db.close()
    before = dump(mutations_path); destination = tmp_path / 'standalone-mutations.sqlite'
    report = migrate_queue(mutations_path, destination, teacher, catalog, {'unitAcceptance': True})
    assert report['pendingMigrated'] > 0 and dump(mutations_path) == before
    store = Store(destination)
    assert [tuple(r) for r in store.db.execute('SELECT * FROM mutation_lineage ORDER BY build_id')] == prior_lineage
    for key, value in prior_settings.items():
        assert store.db.execute('SELECT value FROM collection_settings WHERE key=?', (key,)).fetchone()[0] == value
    for (bid,) in store.db.execute('SELECT id FROM builds'):
        validate_lineage(store.db, bid, catalog)
    store.db.close()
