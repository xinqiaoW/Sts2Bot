from collections import Counter
import copy
import json

import pytest

from test_mutations import catalog, policy, databases
from damage_model.mutations import Generator, validate_lineage
from damage_model.priority_store import AllocationStore
from damage_model.schema import Build
from damage_model.store import Store


def focused_policy(real, policy):
    result = copy.deepcopy(policy)
    result['seed'] = 20260915
    result['target_selection'] = {'name': 'balanced_error_targets_v1', 'targets': {}}
    for r in real.db.execute('SELECT b.body,j.target FROM builds b JOIN jobs j ON j.build_id=b.id'):
        result['target_selection']['targets'][json.loads(r['body'])['act_id']] = [json.loads(r['target'])['id']]
    return result


def test_targeted_balancing_scope_lineage_and_resume(databases, catalog, policy):
    real, target = databases
    policy = focused_policy(real, policy)
    generator = Generator(real, target, catalog, {'fixture': True}, policy)
    before = list(real.db.iterdump())
    report = generator.refill(8)
    assert report['jobs_added'] == 32
    assert all(v['available'] for v in report['target_coverage'].values())
    assert list(real.db.iterdump()) == before
    assert [r[0] for r in target.db.execute('SELECT count(*) FROM mutation_focus GROUP BY act_id,target_id')] == [4, 4]
    for row in target.db.execute('SELECT * FROM mutation_focus'):
        lineage = validate_lineage(target.db, row['build_id'], catalog)
        assert json.loads(lineage['parent_targets']) == [row['target_id']]
        assert {o['target_id'] for o in json.loads(lineage['parent_origins'])} == {row['target_id']}
    restarted = Generator(real, target, catalog, {'fixture': True}, policy)
    restarted.refill(4)
    assert [r[0] for r in target.db.execute('SELECT count(*) FROM mutation_focus GROUP BY act_id,target_id')] == [6, 6]


def test_scope_tampering_is_rejected(databases, catalog, policy):
    real, target = databases
    generator = Generator(real, target, catalog, {'fixture': True}, focused_policy(real, policy))
    generator.refill(1)
    bid = target.db.execute('SELECT build_id FROM mutation_focus').fetchone()[0]
    target.db.execute("UPDATE mutation_focus SET target_id='WRONG_TARGET'")
    with pytest.raises(ValueError, match='escaped'):
        validate_lineage(target.db, bid, catalog)


def test_no_matching_parent_is_explicit_and_does_not_create_jobs(databases, catalog, policy):
    real, target = databases
    policy = focused_policy(real, policy)
    for act in policy['target_selection']['targets']:
        policy['target_selection']['targets'][act] = [next(t['id'] for t in catalog.acts[act]['encounters']
            if t['id'] not in policy['target_selection']['targets'][act])]
    generator = Generator(real, target, catalog, {'fixture': True}, policy)
    with pytest.raises(ValueError, match='No verified real parents'):
        generator.refill(1)
    assert target.counts() == {}


def test_three_queue_cycle_borrowing_and_ownership(databases, tmp_path, catalog, policy):
    real, regular = databases
    target = Store(tmp_path/'targeted.sqlite')
    try:
        Generator(real, regular, catalog, {'fixture': True}, policy).refill(6)
        Generator(real, target, catalog, {'fixture': True}, focused_policy(real, policy)).refill(6)
        row = real.db.execute('SELECT b.body,j.target FROM builds b JOIN jobs j ON j.build_id=b.id LIMIT 1').fetchone()
        real.schedule(Build.from_dict(json.loads(row['body'])), [json.loads(row['target'])], [f'new-{i}' for i in range(40)], {'fixture': True})
        queue = AllocationStore(real, regular, target, {'fixture': True}, offset=0)
        jobs = [queue.claim() for _ in range(16)]
        assert [j['collection_dataset'] for j in jobs] == ['real','real','mutation','targeted'] * 4
        assert Counter(j['collection_dataset'] for j in jobs) == {'real':8,'mutation':4,'targeted':4}
        for job in jobs:
            assert queue.owner(job).db.execute('SELECT lease FROM jobs WHERE id=?', (job['id'],)).fetchone()[0] == job['lease']
        target.db.execute("UPDATE jobs SET status='quarantined' WHERE status='pending'"); target.db.commit()
        borrowed = [queue.claim() for _ in range(4)]
        assert all(j is not None and j['collection_dataset'] != 'targeted' for j in borrowed)
        regular.db.execute("UPDATE jobs SET status='failed' WHERE status='pending'"); regular.db.commit()
        assert queue.claim() is None
    finally:
        target.db.close()


def test_production_focus_list_contains_exactly_43_legal_encounters(catalog):
    from pathlib import Path
    policy = json.loads((Path(__file__).resolve().parents[1]/'configs/mutations-targeted-8s.json').read_text())
    selection = policy['target_selection']['targets']
    assert sum(map(len, selection.values())) == 43
    for act, ids in selection.items():
        assert set(ids) <= {t['id'] for t in catalog.acts[act]['encounters']}
    assert policy['small_probability'] == .6
    assert policy['small'] == {'cards':[1,2], 'relics':[1,2]}
    assert policy['large'] == {'cards':[3,6], 'relics':[1,4]}
