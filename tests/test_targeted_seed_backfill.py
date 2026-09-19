from contextlib import closing
import json

import pytest

from damage_model.mutations import Generator, validate_lineage
from damage_model.store import Store
from test_mutations import catalog, databases, parent_for, policy
from test_encounter_seeds import with_targets
from test_targeted_mutations import focused_policy
from tools.one_off.backfill_targeted_seeds import backfill, check_teacher, connect_readonly


def seed_source(tmp_path, catalog, *, name='real', complete=4):
    store = Store(tmp_path / (name + '.sqlite'))
    build = parent_for(catalog, 'HIVE')
    target = catalog.targets(build)[0]
    seeds = catalog.battle_seeds(build.act_id, target['id'])
    store.schedule(build, [target], seeds, {})
    with store.db:
        for seed in seeds[:complete]:
            store.db.execute("UPDATE jobs SET status='complete',attempts=1,result='synthetic-fixture' WHERE seed=?", (seed,))
        store.db.execute('INSERT INTO target_origins VALUES(?,?,?,?,?)', (build.id, 'run', 25, 26, target['id']))
    return store, build, target, with_targets(catalog, {'HIVE': [target['id']]})


def test_preview_apply_resume_preserves_sources_and_all_output_statuses(tmp_path, catalog):
    source, build, target, expanded = seed_source(tmp_path, catalog)
    sources = [tmp_path/'real.sqlite']
    output_dir = tmp_path/'extra'
    try:
        before = list(source.db.iterdump())
        preview = backfill(sources, output_dir, expanded, {})
        assert preview['jobs_to_add'] == 20 and preview['eligible_pairs'] == 1
        assert preview['eligible_builds'] == preview['stored_unique_builds'] == 1
        assert preview['original_completed_seed_slots'] == 4
        assert preview['extra_seed_slots'] == 20
        assert not output_dir.exists()
        result = backfill(sources, output_dir, expanded, {}, apply=True)
        assert result['jobs_added'] == 20
        assert list(source.db.iterdump()) == before
        output = Store(output_dir/'real.backfill.sqlite')
        try:
            assert output.counts() == {'pending': 20}
            assert tuple(output.db.execute('SELECT * FROM builds').fetchone()) == tuple(source.db.execute('SELECT * FROM builds').fetchone())
            assert list(map(tuple, output.db.execute('SELECT * FROM target_origins'))) == list(map(tuple, source.db.execute('SELECT * FROM target_origins')))
            assert output.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
            assert {r[0] for r in output.db.execute('SELECT seed FROM jobs')} == set(expanded.battle_seeds('HIVE', target['id'])[4:])
            assert all(r[0] is None for r in output.db.execute('SELECT result FROM jobs'))
            # Interrupted collection and diagnosed failures must never be reset.
            with output.db:
                for row, status in zip(output.db.execute('SELECT id FROM jobs').fetchall(),
                                       ['complete', 'running', 'failed', 'quarantined']):
                    output.db.execute('UPDATE jobs SET status=?,attempts=2,result=? WHERE id=?',
                                      (status, 'preserved-' + status, row[0]))
            saved = list(output.db.iterdump())
            resumed = backfill(sources, output_dir, expanded, {}, apply=True)
            assert resumed['jobs_added'] == resumed['jobs_to_add'] == 0
            assert resumed['existing_extra_seeds'] == 20
            assert resumed['eligible_builds'] == resumed['eligible_pairs'] == 1
            assert resumed['sources'][0]['pairs_to_extend'] == 0
            assert resumed['sources'][0]['expected_output_jobs'] == 20
            assert list(output.db.iterdump()) == saved
        finally:
            output.db.close()
    finally:
        source.db.close()


def test_archived_prior_inputs_cover_old_data_and_dedupe_across_versions(tmp_path, catalog):
    old, build, target, expanded = seed_source(tmp_path, catalog, name='v3')
    new = Store(tmp_path/'v4.sqlite')
    try:
        new.add_build(build)
        with new.db:
            new.db.execute('INSERT INTO target_origins VALUES(?,?,?,?,?)', (build.id, 'run', 25, 26, target['id']))
            for row in old.db.execute('SELECT * FROM jobs'):
                new.db.execute('INSERT INTO prior_collected_inputs VALUES(?,?,?,?,?,?,?,?)',
                    (build.id, target['id'], row['seed'], str(tmp_path/'v3.sqlite'), row['id'], 'complete', '{}', 'fixture'))
        # The migrated database alone preserves every input needed for the old batch.
        preview = backfill([tmp_path/'v4.sqlite'], tmp_path/'preview', expanded, {})
        assert preview['jobs_to_add'] == 20 and preview['missing_original_seeds'] == 0
        both = backfill([tmp_path/'v4.sqlite', tmp_path/'v3.sqlite'], tmp_path/'extra', expanded, {}, apply=True)
        assert both['jobs_added'] == 20
        assert [s['jobs_to_add'] for s in both['sources']] == [20, 0]
        assert not (tmp_path/'extra/v3.backfill.sqlite').exists()
    finally:
        old.db.close()
        new.db.close()


def test_one_build_multiple_targets_and_duplicate_sources_are_counted_separately(tmp_path, catalog):
    source, build, first, _ = seed_source(tmp_path, catalog)
    duplicate = Store(tmp_path/'duplicate.sqlite')
    second = catalog.targets(build)[1]
    expanded = with_targets(catalog, {'HIVE': [first['id'], second['id']]})
    try:
        source.schedule(build, [second], catalog.battle_seeds('HIVE', second['id']), {})
        with source.db:
            source.db.execute("UPDATE jobs SET status='complete'")
        source.db.backup(duplicate.db)
        result = backfill([tmp_path/'real.sqlite', tmp_path/'duplicate.sqlite'], tmp_path/'extra', expanded, {})
        assert result['stored_unique_builds'] == result['eligible_builds'] == 1
        assert result['eligible_pairs'] == 2
        assert result['eligible_pairs_per_build'] == {2: 1}
        assert result['original_completed_seed_slots'] == 8
        assert result['extra_seed_slots'] == result['jobs_to_add'] == 40
        assert [s['eligible_pairs'] for s in result['sources']] == [2, 0]
        assert [s['expected_output_jobs'] for s in result['sources']] == [40, 0]
    finally:
        source.db.close()
        duplicate.db.close()


def test_partial_pairs_non_target_pending_only_and_existing_extras(tmp_path, catalog):
    source, build, target, expanded = seed_source(tmp_path, catalog, complete=3)
    try:
        ordinary = catalog.targets(build)[1]
        source.schedule(build, [ordinary], catalog.battle_seeds('HIVE', ordinary['id']), {})
        extra = expanded.battle_seeds('HIVE', target['id'])[4]
        source.schedule(build, [target], [extra], {})
        result = backfill([tmp_path/'real.sqlite'], tmp_path/'extra', expanded, {}, apply=True)
        assert result['jobs_added'] == 19 and result['existing_extra_seeds'] == 1
        assert result['eligible_pairs'] == result['partial_original_pairs'] == result['missing_original_seeds'] == 1
        with closing(connect_readonly(tmp_path/'extra/real.backfill.sqlite')) as output:
            assert {json.loads(r[0])['id'] for r in output.execute('SELECT target FROM jobs')} == {target['id']}
        with source.db:
            source.db.execute("UPDATE jobs SET status='pending'")
        assert backfill([tmp_path/'real.sqlite'], tmp_path/'other', expanded, {})['jobs_to_add'] == 0
    finally:
        source.db.close()


@pytest.mark.parametrize('targeted', [False, True])
def test_mutation_backfill_retains_policy_history_lineage_and_focus(tmp_path, databases, catalog, policy, targeted):
    real, source = databases
    selected_policy = focused_policy(real, policy) if targeted else policy
    Generator(real, source, catalog, {}, selected_policy).refill(4)
    with source.db:
        source.db.execute("UPDATE jobs SET status='complete'")
    targets = focused_policy(real, policy)['target_selection']['targets']
    expanded = with_targets(catalog, targets)
    before = list(source.db.iterdump())
    result = backfill([tmp_path/'mutations.sqlite'], tmp_path/'extra', expanded, {}, apply=True)
    assert result['jobs_added'] == 80
    assert list(source.db.iterdump()) == before
    with closing(connect_readonly(tmp_path/'extra/mutations.backfill.sqlite')) as output:
        for row in output.execute('SELECT id FROM builds'):
            assert tuple(validate_lineage(output, row[0], expanded)) == tuple(validate_lineage(source.db, row[0], expanded))
        assert output.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0


def test_rejects_wrong_teacher_manifest_running_source_and_missing_input(tmp_path, catalog):
    source, _, _, expanded = seed_source(tmp_path, catalog)
    try:
        with pytest.raises(ValueError, match='teacher'):
            backfill([tmp_path/'real.sqlite'], tmp_path/'extra', expanded, {'search_ms': 2000}, apply=True)
        assert not (tmp_path/'extra/real.backfill.sqlite').exists()
        with source.db:
            source.db.execute("UPDATE jobs SET status='running' WHERE id=(SELECT id FROM jobs LIMIT 1)")
        with pytest.raises(ValueError, match='Pause and drain'):
            backfill([tmp_path/'real.sqlite'], tmp_path/'extra', expanded, {}, apply=True)
        with source.db:
            source.db.execute("UPDATE jobs SET status='complete'")
        backfill([tmp_path/'real.sqlite'], tmp_path/'extra', expanded, {}, apply=True)
        expanded.config['battle_seed'] += 1
        with pytest.raises(ValueError, match='matching backfill'):
            backfill([tmp_path/'real.sqlite'], tmp_path/'extra', expanded, {}, apply=True)
        with pytest.raises(FileNotFoundError):
            backfill([tmp_path/'missing.sqlite'], tmp_path/'extra', expanded, {})
    finally:
        source.db.close()


def test_only_existing_adapter_transition_is_compatible():
    old = {'collector_protocol': 2, 'collector_sha256': 'old', 'collector_source': 'old', 'search_ms': 8000}
    new = {**old, 'collector_protocol': 3, 'collector_sha256': 'new', 'collector_source': 'new'}
    check_teacher(old, new)
    with pytest.raises(ValueError, match='teacher'):
        check_teacher(old, {**new, 'search_ms': 2000})


def test_interrupted_queue_batch_rolls_back_and_resumes(tmp_path, databases, catalog, policy, monkeypatch):
    from tools.one_off import backfill_targeted_seeds as module
    real, source = databases
    Generator(real, source, catalog, {}, focused_policy(real, policy)).refill(4)
    with source.db:
        source.db.execute("UPDATE jobs SET status='complete'")
    expanded = with_targets(catalog, focused_policy(real, policy)['target_selection']['targets'])
    original = module.copy_build
    calls = 0

    def interrupted(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError('simulated interruption within a batch')
        return original(*args)

    monkeypatch.setattr(module, 'copy_build', interrupted)
    with pytest.raises(RuntimeError, match='simulated interruption'):
        backfill([tmp_path/'mutations.sqlite'], tmp_path/'extra', expanded, {}, apply=True)
    with closing(connect_readonly(tmp_path/'extra/mutations.backfill.sqlite')) as output:
        assert output.execute('SELECT count(*) FROM jobs').fetchone()[0] == 0
        assert output.execute('SELECT count(*) FROM backfill_origins').fetchone()[0] == 0
    monkeypatch.setattr(module, 'copy_build', original)
    assert backfill([tmp_path/'mutations.sqlite'], tmp_path/'extra', expanded, {}, apply=True)['jobs_added'] == 80
