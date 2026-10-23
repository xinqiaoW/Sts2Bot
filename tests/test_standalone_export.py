import gzip
import json

import pytest

from test_standalone_store import prepare_store
from tools.export_snapshot import export_snapshot


def test_export_preserves_experimental_identity_and_real_recorded_time(tmp_path):
    store, job, result = prepare_store(tmp_path)
    result['elapsedMilliseconds'] = 123
    store.finish(job, result)
    destination = tmp_path / 'snapshot.json.gz'
    manifest = export_snapshot(tmp_path / 'isolated.sqlite', destination)
    with gzip.open(destination, 'rt') as stream:
        data = json.load(stream)
    assert manifest['contains_experimental_results'] is True
    assert data['contains_experimental_results'] is True
    row = data['battles'][0]
    assert row['execution_backend'] == 'standalone-managed-native'
    assert row['validation_scope'] == 'isolated-experiment'
    assert row['result_status'] == 'StandaloneCompleted'
    assert row['provenance'] == result['provenance']
    assert row['finished_turn'] is None  # Old evidence must not invent a turn.
    assert row['finished_at_source'] == 'attempt.finished'
    assert row['elapsed_seconds'] == .123
    assert list(data['teachers'].values()) == [job['teacher']]


@pytest.mark.parametrize('change', ['status', 'hash', 'request'])
def test_export_revalidates_persisted_backend_evidence(tmp_path, change):
    store, job, result = prepare_store(tmp_path)
    result['elapsedMilliseconds'] = 123
    store.finish(job, result)
    if change == 'status': result['status'] = 'Passed'
    if change == 'hash': result['provenance']['hostSha256'] = 'd' * 64
    if change == 'request': result['collectionRequest']['seed'] = 'wrong'
    store.db.execute('UPDATE jobs SET result=?', (json.dumps(result),))
    store.db.commit()
    with pytest.raises(ValueError):
        export_snapshot(tmp_path / 'isolated.sqlite', tmp_path / 'snapshot.json.gz')
    assert not (tmp_path / 'snapshot.json.gz').exists()


def test_training_cache_accepts_and_marks_standalone(tmp_path):
    import pyarrow.parquet as pq
    from train.snapshot import export_source, merge_sources
    store, job, result = prepare_store(tmp_path)
    result['elapsedMilliseconds'] = 123
    store.finish(job, result)
    source = {'name': 'isolated', 'kind': 'real', 'db': str(tmp_path / 'isolated.sqlite')}
    meta = export_source(source, tmp_path / 'cache')
    assert meta['contains_experimental_results'] is True
    config = {'sources': [source], 'teacher_compatibility_keys': [], 'split_buckets': {'train': 100}}
    manifest = merge_sources(config, tmp_path / 'cache', tmp_path / 'training')
    assert manifest['contains_experimental_results'] is True
    assert list(manifest['teachers'].values()) == [job['teacher']]
    row = pq.read_table(tmp_path / 'training/battles.parquet').to_pylist()[0]
    assert row['finished_turn'] is None and row['finished_at']
    assert row['elapsed_seconds'] == pytest.approx(.123)


@pytest.mark.parametrize('change', ['status', 'hash', 'request'])
def test_training_cache_rejects_forged_backend(tmp_path, change):
    from train.snapshot import export_source
    store, job, result = prepare_store(tmp_path)
    store.finish(job, result)
    if change == 'status': result['status'] = 'Passed'
    if change == 'hash': result['provenance']['hostSha256'] = 'd' * 64
    if change == 'request': result['collectionRequest']['seed'] = 'wrong'
    store.db.execute('UPDATE jobs SET result=?', (json.dumps(result),))
    store.db.commit()
    with pytest.raises(ValueError):
        export_source({'name': 'bad', 'kind': 'real', 'db': str(tmp_path / 'isolated.sqlite')}, tmp_path / 'cache')


@pytest.mark.parametrize('key,value', [
    ('execution_backend', 'native-wine'), ('standalone_host_sha256', 'd' * 64),
    ('standalone_unlock_state', 'progress-snapshot'), ('progress_snapshot_sha256', 'e' * 64),
    ('validation_scope', 'production')])
def test_training_merge_requires_backend_identity_even_with_old_config(tmp_path, key, value):
    from train.snapshot import merge_sources
    from test_train_pipeline import write_cache
    teacher = {'execution_backend': 'standalone-managed-native', 'standalone_host_sha256': 'a' * 64,
               'standalone_unlock_state': 'all', 'validation_scope': 'isolated-experiment'}
    write_cache(tmp_path, 'a', 'real', {}, [], [], teacher=teacher)
    write_cache(tmp_path, 'b', 'real', {}, [], [], teacher={**teacher, key: value})
    config = {'sources': [{'name': 'a'}, {'name': 'b'}], 'teacher_compatibility_keys': [],
              'split_buckets': {'train': 100}}
    with pytest.raises(ValueError, match='Incompatible teacher'):
        merge_sources(config, tmp_path, tmp_path / 'output')
