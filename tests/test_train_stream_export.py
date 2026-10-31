import hashlib
import gzip
import json
import sqlite3

import pyarrow.parquet as pq
import pytest

from damage_model.schema import Build, Card
from train.stream_export import export_or_reuse, export_source, table_rows, validated_battle


def collection(tmp_path):
    path = tmp_path / 'collection.sqlite'
    build = Build('OVERGROWTH', 1, (Card('STRIKE_SILENT'),), (), (), 'test')
    teacher = {'collector_protocol': 3, 'search_ms': 8000}
    observation = {'complete': True, 'initialHp': 70, 'initialMaxHp': 70,
                   'finalHp': 60, 'finalMaxHp': 70, 'netHpLoss': 10, 'playerDied': False,
                   'initialBuild': {'cards': [{'id': 'STRIKE_SILENT', 'upgradeLevel': 0,
                                              'persistentState': {}, 'enchantmentAmount': 0}]}}
    result = {'status': 'Passed', 'combatEnded': True, 'trainingObservation': observation}
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE builds(id TEXT PRIMARY KEY,body TEXT);
            CREATE TABLE jobs(id TEXT PRIMARY KEY,build_id TEXT,target TEXT,seed TEXT,
                              teacher TEXT,status TEXT,result TEXT,attempts INTEGER);
            CREATE INDEX jobs_status ON jobs(status);
            CREATE TABLE attempts(job_id TEXT,finished REAL,status TEXT);
            CREATE INDEX attempts_recent ON attempts(finished,status,job_id);
            CREATE TABLE build_origins(build_id TEXT,run_hash TEXT);
        ''')
        db.execute('INSERT INTO builds VALUES(?,?)', (build.id, json.dumps(build.to_dict())))
        db.execute('INSERT INTO build_origins VALUES(?,?)', (build.id, 'source-run'))
        for jid, status in [('good', 'complete'), ('pending', 'pending')]:
            db.execute('INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?)',
                       (jid, build.id, json.dumps({'id': 'FLYCONID_NORMAL'}), jid,
                        json.dumps(teacher), status, json.dumps(result), 1))
    return path, build, result


def test_stream_export_reads_all_statuses_but_exports_only_valid_completed_labels(tmp_path):
    path, build, _ = collection(tmp_path)
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    out = tmp_path / 'cache'
    meta = export_source({'name': 'real', 'kind': 'real', 'db': str(path)}, out, flush_rows=1)
    assert meta['job_counts'] == {'complete': 1, 'pending': 1}
    assert meta['rows'] == 1 and meta['edges'] == 1 and meta['verify_cards']
    assert meta['rejected_counts'] == {}
    row = pq.read_table(out / 'real.battles.parquet').to_pylist()[0]
    assert row['job_id'] == 'good' and row['hp_loss'] == 10 and row['max_hp'] == 70
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_prepared_cache_is_reused_without_reading_the_database(tmp_path):
    path, _, _ = collection(tmp_path)
    source = {'name': 'real', 'kind': 'real', 'db': str(path)}
    cache = tmp_path / 'cache'
    first = export_or_reuse(source, cache)
    path.unlink()
    second = export_or_reuse(source, cache)
    assert first == second and second['rows'] == 1
    with pytest.raises(ValueError, match='validation policy differs'):
        export_or_reuse({**source, 'recover_invalid_rows': True}, cache)


@pytest.mark.parametrize('cached_build', [True, False])
def test_backfill_uses_verified_parent_builds_and_falls_back_without_losing_labels(tmp_path, cached_build):
    path, build, _ = collection(tmp_path)
    cache = tmp_path/'snapshot/sources'
    cache.mkdir(parents=True)
    parent_db = tmp_path/'native.sqlite'
    rows = int(cached_build)
    (cache/'parent.meta.json').write_text(json.dumps({'name': 'parent', 'db': str(parent_db),
                                                    'rows': rows, 'verify_cards': True}))
    with gzip.open(cache/'parent.builds.json.gz', 'wt') as stream:
        json.dump({'builds': {build.id: build.to_dict()} if cached_build else {}}, stream)
    (tmp_path/'verified-native-cache.json').write_text(json.dumps({
        'state': 'verified', 'cache': str(cache), 'sources': {'parent': rows}}))
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE collection_settings(key TEXT,value TEXT)')
        db.execute('INSERT INTO collection_settings VALUES(?,?)',
                   ('targeted_seed_backfill', json.dumps({'source': str(parent_db)})))
        if cached_build:
            # The planned state is already in the verified frozen cache. The
            # label and source-run edges still have to come from this queue.
            db.execute("UPDATE builds SET body='unused damaged body'")
    source = {'name': 'backfill', 'kind': 'real', 'db': str(path), 'verified_build_sources': ['parent']}
    meta = export_source(source, cache)
    assert meta['rows'] == 1 and meta['edges'] == 1
    assert meta['db_build_fallbacks'] == int(not cached_build)
    row = pq.read_table(cache/'backfill.battles.parquet').to_pylist()[0]
    assert row['hp_loss'] == 10 and row['source'] == 'backfill'


def test_invalid_label_is_fatal_by_default_and_accounted_for_in_recovery(tmp_path):
    path, _, result = collection(tmp_path)
    result['trainingObservation']['netHpLoss'] = 99
    with sqlite3.connect(path) as db:
        db.execute("UPDATE jobs SET result=? WHERE id='good'", (json.dumps(result),))
    source = {'name': 'real', 'kind': 'real', 'db': str(path)}
    with pytest.raises(ValueError, match='Invalid HP loss'):
        export_source(source, tmp_path / 'strict')
    meta = export_source({**source, 'recover_invalid_rows': True}, tmp_path / 'recovery')
    assert meta['rows'] == 0
    assert meta['job_counts']['complete'] == 1
    rejected = [json.loads(line) for line in (tmp_path / 'recovery/real.rejected.jsonl').read_text().splitlines()]
    assert len(rejected) == 1 and rejected[0]['id'] == 'good'
    assert rejected[0]['reason'] == 'invalid_completed_label'


def test_range_recovery_bisects_corruption_and_keeps_neighbors():
    class BrokenConnection:
        def execute(self, sql, args=()):
            if not args:
                return type('Cursor', (), {'fetchone': lambda self: (5,)})()
            low, high = args
            if low <= 3 <= high:
                error = sqlite3.DatabaseError('database disk image is malformed')
                error.sqlite_errorcode = sqlite3.SQLITE_CORRUPT
                raise error
            return type('Cursor', (), {'fetchall': lambda self: list(range(low, high+1))})()
    rejected = []
    rows = list(table_rows(BrokenConnection(), 'jobs', 'id', recover=True, reject=rejected.append, batch=5))
    assert rows == [1, 2, 4, 5]
    assert len(rejected) == 1 and rejected[0]['rowid'] == 3


def test_busy_read_is_never_discarded_as_corrupt_data():
    class BusyConnection:
        def execute(self, sql, args=()):
            if not args:
                return type('Cursor', (), {'fetchone': lambda self: (2,)})()
            error = sqlite3.OperationalError('database is locked')
            error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise error
    rejected = []
    with pytest.raises(sqlite3.OperationalError):
        list(table_rows(BusyConnection(), 'jobs', 'id', recover=True, reject=rejected.append))
    assert rejected == []


def test_recovered_standalone_label_keeps_missing_timestamp_explicit(tmp_path):
    path, build, result = collection(tmp_path)
    teacher = {'collector_protocol': 3, 'search_ms': 8000, 'execution_backend': 'standalone-managed-native',
               'validation_scope': 'isolated-experiment', 'standalone_unlock_state': 'all',
               'game_sha256': 'a'*64, 'collector_sha256': 'b'*64, 'standalone_host_sha256': 'c'*64}
    result.update(status='StandaloneCompleted', runId='run', productionReady=False,
                  productionLabels=False,
                  provenance={'backend': 'standalone-managed-native', 'gameSha256': 'a'*64,
                              'solverSha256': 'b'*64, 'hostSha256': 'c'*64,
                              'collectorProtocol': 3, 'testMode': True, 'unlockState': 'all',
                              'productionValidated': False},
                  collectionRequest={'runId': 'run', 'seed': 'seed', 'encounterId': 'FLYCONID_NORMAL'})
    row = {'teacher': json.dumps(teacher), 'target': json.dumps({'id': 'FLYCONID_NORMAL'}),
           'result': json.dumps(result), 'seed': 'seed', 'id': 'job', 'build_id': build.id, 'attempts': 1}
    source = {'name': 'old', 'kind': 'real'}
    with pytest.raises(ValueError, match='Missing completion timestamp'):
        validated_battle(row, source, {build.id: build.to_dict()}, {})
    battle, _, _ = validated_battle(row, {**source, 'recover_invalid_rows': True}, {build.id: build.to_dict()}, {})
    assert battle['finished_at'] is None and battle['hp_loss'] == 10
    result['provenance']['hostSha256'] = 'd'*64
    with pytest.raises(ValueError, match='provenance mismatch'):
        validated_battle({**row, 'result': json.dumps(result)}, {**source, 'recover_invalid_rows': True},
                         {build.id: build.to_dict()}, {})
