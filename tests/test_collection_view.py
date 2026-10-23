import copy
from contextlib import closing
import hashlib
import json
import sqlite3

import pytest

from damage_model.schema import Build
from tools import collection_view
from tools.collection_view import CollectionView, read_db
from test_standalone_store import prepare_store


@pytest.fixture
def viewer(tmp_path):
    directory = tmp_path / 'instance'
    (directory / 'db').mkdir(parents=True)
    for dataset in ('real', 'mutations', 'targeted'):
        folder = tmp_path / dataset
        folder.mkdir()
        store, job, result = prepare_store(folder)
        # More than four seeds, with pending and quarantined jobs mixed in.
        target = {**job['target'], 'room_type': 'Elite', 'monsters': []}
        store.db.execute('UPDATE jobs SET target=?', (json.dumps(target),))
        store.db.commit()
        job['target'] = target
        result['elapsedMilliseconds'] = 1234
        store.finish(job, result)
        body = json.loads(store.db.execute('SELECT body FROM builds').fetchone()[0])
        store.schedule(Build.from_dict(body), [target], [f'seed-{i}' for i in range(23)], job['teacher'])
        with sqlite3.connect(directory / 'db' / (dataset + '.sqlite')) as dest:
            store.db.backup(dest)
        store.db.close()
    view = CollectionView(directory, tmp_path / 'index.sqlite')
    with closing(sqlite3.connect(view.cache)) as writer:
        writer.row_factory = sqlite3.Row
        view.refresh_metadata(writer)
        for name in view.paths:
            while view.sync_chunk(writer, name): pass
    return view


def test_read_only_index_aggregates_three_queues_and_actual_seed_count(viewer):
    hashes = {n: hashlib.sha256(p.read_bytes()).hexdigest() for n, p in viewer.paths.items()}
    o = viewer.overview({})
    assert o['summary']['battles'] == 3
    assert o['summary']['mean_loss'] == 40
    assert o['summary']['median_loss'] == 40
    assert o['summary']['deaths'] == 0
    assert o['summary']['flagged'] == 0
    assert o['histogram'] == [{'loss': 40, 'n': 3}]
    b = viewer.battles({'dataset': 'targeted'})['rows'][0]
    detail = viewer.detail({'dataset': 'targeted', 'build': b['build_id']})
    assert len(detail['seeds']) == 24
    assert detail['targets'][0]['planned'] == 24
    assert detail['targets'][0]['n'] == 1
    assert sum(s['status'] == 'pending' for s in detail['seeds']) == 23
    assert next(s for s in detail['seeds'] if s['status'] == 'complete')['turns'] is None
    assert detail['build']['card_items'][0]['persistent_state'] == {'CombatsSeen': 1}
    for n, p in viewer.paths.items():
        assert hashlib.sha256(p.read_bytes()).hexdigest() == hashes[n]
        with closing(read_db(p)) as db:
            with pytest.raises(sqlite3.OperationalError, match='readonly'):
                db.execute("UPDATE jobs SET status='complete'")


def test_incremental_refresh_is_idempotent_and_sees_new_wal_results(viewer):
    with sqlite3.connect(viewer.paths['real']) as db:
        row = db.execute("SELECT id,build_id,target,seed,teacher FROM jobs WHERE status='pending' LIMIT 1").fetchone()
        result = viewer.raw({'dataset': 'real', 'job': viewer.battles({'dataset': 'real'})['rows'][0]['job_id']})['result']
        result = copy.deepcopy(result)
        result['collectionRequest']['seed'] = row[3]
        result['trainingObservation'].update(finalHp=0, netHpLoss=70, playerDied=True)
        db.execute('PRAGMA journal_mode=WAL')
        db.execute("UPDATE jobs SET status='complete',result=? WHERE id=?", (json.dumps(result), row[0]))
        db.execute("INSERT INTO attempts(job_id,status,result,finished) VALUES(?,'complete',?,123456)", (row[0], json.dumps(result)))
    with closing(sqlite3.connect(viewer.cache)) as writer:
        writer.row_factory = sqlite3.Row
        # Results newer than metadata wait until their build/task metadata is read.
        viewer.sync_chunk(writer, 'real')
        assert viewer.overview({})['summary']['battles'] == 3
        viewer.refresh_metadata(writer)
        viewer.sync_chunk(writer, 'real')
        viewer.sync_chunk(writer, 'real')
    assert viewer.overview({})['summary']['battles'] == 4
    assert viewer.overview({'dataset': 'real'})['summary']['mean_loss'] == 55
    rows = viewer.battles({'outcome': 'dead', 'loss_min': '60', 'sort': 'loss_desc'})['rows']
    assert len(rows) == 1 and rows[0]['loss'] == 70
    assert viewer.battles({'q': "' OR 1=1 --"})['total'] == 0
    with pytest.raises(ValueError): viewer.battles({'sort': 'loss; DROP TABLE battles'})


def test_overview_uses_one_snapshot_while_results_arrive(viewer, monkeypatch):
    original = read_db
    changed = False

    class ConcurrentReader:
        def __init__(self, connection): self.connection = connection
        def close(self): self.connection.close()
        def execute(self, sql, parameters=()):
            nonlocal changed
            if not changed and 'GROUP BY loss ORDER BY loss' in sql:
                # Commit a real index update between the summary and histogram.
                with sqlite3.connect(viewer.cache) as writer:
                    writer.execute("UPDATE battles SET loss=41 WHERE dataset='real'")
                changed = True
            return self.connection.execute(sql, parameters)

    monkeypatch.setattr(collection_view, 'read_db', lambda path: ConcurrentReader(original(path)))
    overview = viewer.overview({})
    assert changed
    assert overview['summary']['mean_loss'] == 40
    assert overview['histogram'] == [{'loss': 40, 'n': 3}]
    assert all(target['mean_loss'] == 40 for target in overview['targets'])
    assert sum(r['n'] for r in overview['histogram']) == overview['summary']['battles']
    assert viewer.overview({})['summary']['mean_loss'] == pytest.approx(121 / 3)


def test_corrupt_completed_label_is_visible_as_flagged_not_repaired(viewer):
    row = viewer.battles({'dataset': 'real'})['rows'][0]
    raw = viewer.raw({'dataset': 'real', 'job': row['job_id']})['result']
    raw['trainingObservation']['netHpLoss'] = 99
    with sqlite3.connect(viewer.paths['real']) as db:
        db.execute('UPDATE attempts SET result=?', (json.dumps(raw),))
    with sqlite3.connect(viewer.cache) as db:
        db.row_factory = sqlite3.Row
        db.execute("UPDATE sources SET attempt_cursor=0 WHERE dataset='real'")
        viewer.sync_chunk(db, 'real')
    bad = viewer.battles({'outcome': 'flagged'})['rows']
    assert len(bad) == 1 and bad[0]['loss'] == 99
    assert 'Invalid HP loss' in bad[0]['flags']
    # Viewer never rewrites either the stored result or the submitted input.
    assert viewer.raw({'dataset': 'real', 'job': row['job_id']})['result']['trainingObservation']['netHpLoss'] == 40


@pytest.mark.parametrize('change', ['hash', 'scope', 'card'])
def test_compact_index_preserves_evidence_needed_for_validation(viewer, change):
    row = viewer.battles({'dataset': 'real'})['rows'][0]
    result = viewer.raw({'dataset': 'real', 'job': row['job_id']})['result']
    if change == 'hash': result['provenance']['hostSha256'] = 'd' * 64
    if change == 'scope': result['productionReady'] = True
    if change == 'card': result['trainingObservation']['initialBuild']['cards'][0]['persistentState'] = {}
    with sqlite3.connect(viewer.paths['real']) as source:
        source.execute('UPDATE attempts SET result=?', (json.dumps(result),))
    with sqlite3.connect(viewer.cache) as writer:
        writer.row_factory = sqlite3.Row
        writer.execute("UPDATE sources SET attempt_cursor=0 WHERE dataset='real'")
        viewer.sync_chunk(writer, 'real')
    bad = viewer.battles({'outcome': 'flagged'})['rows']
    assert len(bad) == 1 and bad[0]['dataset'] == 'real'
    assert viewer.overview({})['summary']['battles'] == 3


def test_malformed_attempt_does_not_stall_backfill_or_remain_as_valid_sample(viewer):
    row = viewer.battles({'dataset': 'real'})['rows'][0]
    original = viewer.raw({'dataset': 'real', 'job': row['job_id']})['result']
    with sqlite3.connect(viewer.paths['real']) as source:
        source.execute("UPDATE attempts SET result='broken json'")
    with sqlite3.connect(viewer.cache) as writer:
        writer.row_factory = sqlite3.Row
        writer.execute("UPDATE sources SET attempt_cursor=0 WHERE dataset='real'")
        viewer.sync_chunk(writer, 'real')
        assert writer.execute("SELECT attempt_cursor FROM sources WHERE dataset='real'").fetchone()[0] == 1
    assert viewer.overview({'dataset': 'real'})['summary']['battles'] == 0
    assert viewer.issues({'dataset': 'real'})['rows'][0]['status'] == 'index_error'
    with sqlite3.connect(viewer.paths['real']) as source:
        source.execute('UPDATE attempts SET result=?', (json.dumps(original),))
    with sqlite3.connect(viewer.cache) as writer:
        writer.row_factory = sqlite3.Row
        writer.execute("UPDATE sources SET attempt_cursor=0 WHERE dataset='real'")
        viewer.sync_chunk(writer, 'real')
    assert viewer.overview({'dataset': 'real'})['summary']['battles'] == 1
    assert viewer.issues({'dataset': 'real'})['rows'] == []
