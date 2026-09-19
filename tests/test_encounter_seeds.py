import json
from pathlib import Path

import pytest

from damage_model.catalog import Catalog
from damage_model.mutations import Generator
from damage_model.run_import import import_run
from damage_model.schema import digest
from damage_model.store import Store
from damage_model.target_scope import migrate_window, plan_window
from test_run_import import catalog, run
from test_mutations import databases, policy
from test_targeted_mutations import focused_policy

ROOT = Path(__file__).resolve().parents[1]


def with_targets(catalog, targets):
    return Catalog(catalog.raw, {**catalog.config, 'encounter_seed_policy': {
        'seeds_per_pair': 24, 'targets': targets}})


def test_production_policy_uses_exact_focus_list_and_preserves_seed_prefix(tmp_path, monkeypatch):
    # Resolve the targets file beside the config, independent of the caller's cwd.
    monkeypatch.chdir(tmp_path)
    cat = Catalog.load(ROOT/'catalogs/game-0.111.0.raw.json', ROOT/'configs/real-runs-8s.json')
    targets = json.loads((ROOT/'configs/mutations-targeted-8s.json').read_text())['target_selection']['targets']
    expected = {(act, tid) for act, ids in targets.items() for tid in ids}
    assert len(expected) == 43 and set(cat.encounter_seed_counts) == expected
    original = [digest(['battle', cat.config['battle_seed'], j])[:16] for j in range(4)]
    for act, spec in cat.acts.items():
        for target in spec['encounters']:
            seeds = cat.battle_seeds(act, target['id'])
            assert seeds[:4] == original
            assert len(seeds) == len(set(seeds)) == (24 if (act, target['id']) in expected else 4)
    assert Catalog(cat.raw, cat.config).encounter_seed_counts == cat.encounter_seed_counts


@pytest.mark.parametrize('count,targets', [(True, {'HIVE': ['TUNNELER_WEAK']}),
    (3, {'HIVE': ['TUNNELER_WEAK']}), (24, {'HIVE': ['UNKNOWN']}),
    (24, {'HIVE': ['TUNNELER_WEAK', 'TUNNELER_WEAK']}), (24, {})])
def test_invalid_seed_policy_fails_at_load(catalog, count, targets):
    with pytest.raises(ValueError, match='seed policy'):
        Catalog(catalog.raw, {**catalog.config, 'encounter_seed_policy': {
            'seeds_per_pair': count, 'targets': targets}})


def test_import_mixed_targets_preserves_old_jobs_and_does_not_backfill_cached_runs(catalog, run, tmp_path):
    targets = catalog.acts['OVERGROWTH']['encounters'][:2]
    run['map_point_history'][0][2]['rooms'] = [{'model_id': 'ENCOUNTER.' + targets[1]['id']}]
    store = Store(tmp_path/'real.sqlite')
    try:
        old_report = import_run(store, catalog, {}, run, 'old', 'fixture')
        before = {r['id']: tuple(r) for r in store.db.execute('SELECT * FROM jobs')}
        expanded = with_targets(catalog, {'OVERGROWTH': [targets[0]['id']]})
        assert import_run(store, expanded, {}, run, 'old', 'fixture')['scheduled_now'] == 0
        assert before == {r['id']: tuple(r) for r in store.db.execute('SELECT * FROM jobs')}
        report = import_run(store, expanded, {}, run, 'new-source', 'fixture')
        assert report['scheduled_now'] == 0
        assert report['duplicate_build_floors'] == 2
        assert store.counts()['pending'] == old_report['scheduled_now']
        for row in store.db.execute('SELECT * FROM jobs'):
            if row['id'] in before:
                assert tuple(row) == before[row['id']]
        assert import_run(store, expanded, {}, run, 'new-source', 'fixture')['scheduled_now'] == 0
        counts = list(store.db.execute("SELECT json_extract(target,'$.id'),count(*) FROM jobs GROUP BY build_id,target"))
        assert sorted(r[1] for r in counts) == [4, 4, 4, 4]
        assert store.db.execute("SELECT count(*) FROM build_origins WHERE run_hash='new-source'").fetchone()[0] == 2
        assert plan_window(store.db, expanded)['report']['selected_battles'] == 56
        # Explicit migration is separate from ordinary source import.
        assert migrate_window(store, expanded, {})['added'] == 40
        fresh = Store(tmp_path/'fresh.sqlite')
        try:
            assert import_run(fresh, expanded, {}, run, 'fresh', 'fixture')['scheduled_now'] == 56
            assert import_run(fresh, expanded, {}, run, 'repeated-fresh', 'fixture')['scheduled_now'] == 0
        finally:
            fresh.db.close()
    finally:
        store.db.close()


def test_duplicate_build_does_not_add_a_new_opponent(catalog, run, tmp_path):
    from copy import deepcopy
    store = Store(tmp_path/'real.sqlite')
    try:
        import_run(store, catalog, {}, run, 'first', 'fixture')
        before = list(store.db.execute('SELECT * FROM jobs'))
        changed = deepcopy(run)
        changed['map_point_history'][0][2]['rooms'] = [
            {'model_id': 'ENCOUNTER.' + catalog.acts['OVERGROWTH']['encounters'][1]['id']}]
        assert import_run(store, catalog, {}, changed, 'other-opponent', 'fixture')['scheduled_now'] == 0
        assert before == list(store.db.execute('SELECT * FROM jobs'))
    finally:
        store.db.close()


def test_real_import_skips_builds_already_in_related_queues(catalog, run, tmp_path):
    known, fresh = Store(tmp_path/'known.sqlite'), Store(tmp_path/'fresh.sqlite')
    try:
        import_run(known, catalog, {}, run, 'known', 'fixture')
        fresh.avoid_build_stores = (known,)
        result = import_run(fresh, catalog, {}, run, 'new-source', 'fixture')
        assert result['scheduled_now'] == 0 and result['duplicate_build_floors'] == 2
        assert fresh.db.execute('SELECT count(*) FROM builds').fetchone()[0] == 0
        assert fresh.db.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
    finally:
        known.db.close()
        fresh.db.close()


@pytest.mark.parametrize('targeted', [False, True])
def test_both_mutation_generators_use_per_encounter_seeds(databases, catalog, policy, targeted):
    real, destination = databases
    focus = focused_policy(real, policy)
    # Only one parent's encounter is expanded. The other remains four seeds.
    act, ids = next(iter(focus['target_selection']['targets'].items()))
    expanded = with_targets(catalog, {act: ids})
    Generator(real, destination, expanded, {'fixture': True}, focus if targeted else policy).refill(20)
    observed = set()
    for row in destination.db.execute('SELECT b.body,j.target,count(*) AS n FROM builds b JOIN jobs j ON j.build_id=b.id GROUP BY b.id,j.target'):
        size = 24 if json.loads(row['body'])['act_id'] == act else 4
        assert row['n'] == size
        observed.add(size)
    assert observed == {4, 24}
