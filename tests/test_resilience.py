"""Synthetic queues prove isolation cannot rewrite labels or stop unrelated jobs."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from damage_model.resilience import NATIVE_FAILURES, native_failure_policy, preserve_failure
from damage_model.schema import Build, Card, Relic, digest
from damage_model.store import Store
from damage_model.worker import request_for

POLICY = {'name': 'retry_then_quarantine_v1', 'max_attempts': 3,
          'evidence_directory': 'evidence/native-failures-v3'}


@pytest.fixture
def queue(tmp_path):
    store = Store(tmp_path / 'synthetic.sqlite')
    build = Build('OVERGROWTH', 1, (Card('DEFEND_SILENT', 1),),
                  (Relic('RING_OF_THE_SNAKE'),), (), 'synthetic-only')
    store.schedule(build, [{'id': 'SYNTHETIC_TARGET'}], ['bad', 'good'], {'test': True})
    yield store
    store.db.close()


def record(tmp_path, status='Failed'):
    evidence = tmp_path / 'failure.json'
    result = {'status': status, 'runId': 'a' * 32, 'trainingObservation': None,
              'error': 'synthetic native failure'}
    evidence.write_text(json.dumps(result))
    return result, dict(max_attempts=3, reason='Synthetic diagnosis', evidence=str(evidence))


def success(job):
    return {'status': 'Passed', 'combatEnded': True, 'trainingObservation': {
        'complete': True, 'initialHp': 70, 'initialMaxHp': 70, 'finalHp': 53, 'finalMaxHp': 70,
        'netHpLoss': 17, 'playerDied': False, 'initialBuild': {
            'character': 'SILENT', 'ascension': 10, 'actId': 'OVERGROWTH',
            'cards': [{'id': 'DEFEND_SILENT', 'upgradeLevel': 1}],
            'relics': [{'id': 'RING_OF_THE_SNAKE', 'counters': {}}]}}}


@pytest.mark.parametrize('status', sorted(NATIVE_FAILURES))
def test_bound_preserves_original_status_and_other_jobs(queue, tmp_path, status):
    result, args = record(tmp_path, status)
    first_id = None
    for attempt in range(3):
        job = queue.claim()
        first_id = first_id or job['id']
        assert job['id'] == first_id
        assert queue.retry_or_quarantine_native(job, result, **args) == ('retry' if attempt < 2 else 'quarantined')
        assert queue.counts().get('failed', 0) == 0
    rows = [dict(r) for r in queue.db.execute('SELECT * FROM attempts ORDER BY id')]
    assert [r['status'] for r in rows] == ['retry', 'retry', 'failed']
    assert all(json.loads(r['result']) == result for r in rows)
    audit = dict(queue.db.execute('SELECT * FROM job_quarantines').fetchone())
    assert audit['attempts_sha256'] == digest(rows)
    assert dict(queue.db.execute('SELECT * FROM jobs WHERE id=?', (first_id,)).fetchone()) == {
        **json.loads(audit['original_job']), 'status': 'quarantined'}
    job = queue.claim()
    assert job['seed'] == 'good'
    assert queue.finish(job, success(job)) == 'complete'
    assert queue.counts() == {'complete': 1, 'quarantined': 1}
    assert len(list(queue.rows())) == 1


def test_retry_then_success_and_stale_submit(queue, tmp_path):
    result, args = record(tmp_path)
    old = queue.claim()
    queue.retry_or_quarantine_native(old, result, **args)
    job = queue.claim()
    before = [tuple(r) for r in queue.db.execute('SELECT * FROM attempts')]
    with pytest.raises(ValueError, match='Stale'):
        queue.retry_or_quarantine_native(old, result, **args)
    assert [tuple(r) for r in queue.db.execute('SELECT * FROM attempts')] == before
    assert queue.finish(job, success(job)) == 'complete'
    assert not queue.counts().get('quarantined')


@pytest.mark.parametrize('change', [{'status': 'Passed'}, {'status': 'InvalidObservation'},
                                   {'trainingObservation': {'complete': True}}])
def test_validation_failures_and_success_cannot_be_isolated(queue, tmp_path, change):
    result, args = record(tmp_path)
    job = queue.claim()
    with pytest.raises(ValueError):
        queue.retry_or_quarantine_native(job, {**result, **change}, **args)
    assert queue.counts() == {'pending': 1, 'running': 1}
    assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0


def test_evidence_must_exist_and_request_unchanged(queue, tmp_path):
    result, args = record(tmp_path)
    job = queue.claim()
    args['evidence'] += '.missing'
    with pytest.raises(ValueError): queue.retry_or_quarantine_native(job, result, **args)
    config = {'short_search_budget_ms': 8000, 'search_dop': 1, 'battle_timeout_seconds': 120}
    first = request_for(job, config); second = request_for(job, {**config, 'native_failure_policy': POLICY})
    first.pop('runId'); second.pop('runId')
    assert first == second
    assert native_failure_policy(config) is None
    assert native_failure_policy({**config, 'native_failure_policy': POLICY}) == POLICY


def test_diagnostic_log_only_contains_current_attempt(queue, tmp_path):
    job = queue.claim(); result, _ = record(tmp_path)
    log = tmp_path / 'game.log'; previous = b'OLD REQUEST\n'
    current = b'CURRENT REQUEST\nSEARCH_FAILURE field=hp expected=10 actual=8\n'
    log.write_bytes(previous + current)
    manifest, reason = preserve_failure(SimpleNamespace(log_path=log), job, result, len(previous), tmp_path / 'audit')
    assert (Path(manifest).parent / 'native.log').read_bytes() == current
    assert json.loads(Path(manifest).read_text())['result'] == result
    assert 'field=hp' in reason


def cleanup_timeout():
    return {**success(None), 'status': 'Failed', 'stage': 'cleanup',
            'error': 'System.TimeoutException: cleanup deadline\n'
                     '   at CombatSolver.UnattendedTestRunner.EnsureWithinDeadline()'}


@pytest.mark.parametrize('change', [
    {'status': 'Passed'}, {'status': 'InvalidObservation'}, {'status': 'Timeout'},
    {'stage': 'wait_combat_end'}, {'combatEnded': False},
    {'error': 'System.TimeoutException: unrelated timeout'},
    {'error': 'System.InvalidOperationException: UnattendedTestRunner.EnsureWithinDeadline()'},
])
def test_complete_observation_does_not_bypass_failure_guard(queue, tmp_path, change):
    _, args = record(tmp_path)
    job = queue.claim()
    with pytest.raises(ValueError):
        queue.retry_or_quarantine_native(job, {**cleanup_timeout(), **change}, **args)
    assert queue.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
    assert queue.counts() == {'pending': 1, 'running': 1}


def test_cleanup_timeout_retries_without_exporting_observation(queue, tmp_path):
    _, args = record(tmp_path)
    result = cleanup_timeout()
    for attempt in range(3):
        job = queue.claim()
        assert queue.retry_or_quarantine_native(job, result, **args) == ('retry' if attempt < 2 else 'quarantined')
        assert list(queue.rows()) == []
    rows = [dict(r) for r in queue.db.execute('SELECT * FROM attempts ORDER BY id')]
    assert [r['status'] for r in rows] == ['retry', 'retry', 'failed']
    assert all(json.loads(r['result']) == result for r in rows)
    audit = queue.db.execute('SELECT * FROM job_quarantines').fetchone()
    assert audit['attempts_sha256'] == digest(rows)
    assert queue.finish(queue.claim(), success(None)) == 'complete'
    assert len(list(queue.rows())) == 1


@pytest.mark.parametrize('post_combat_timeout', [False, True])
def test_worker_keeps_collecting_after_repeat_failure(queue, tmp_path, monkeypatch, post_combat_timeout):
    pytest.importorskip('fcntl')
    from damage_model import worker
    monkeypatch.chdir(tmp_path)
    runtime = tmp_path / 'runtime.json'; runtime.write_text('{}')
    class FakeGame:
        def __init__(self, **kwargs):
            self.data_dir = tmp_path
            self.log_path = tmp_path / 'game.log'
            self.requests = []
            self.stops = 0
        def stop(self): self.stops += 1
        def run(self, request):
            self.requests.append(copy.deepcopy(request))
            self.log_path.write_text('Synthetic test log\n')
            if request['seed'] == 'bad':
                if post_combat_timeout:
                    return {**cleanup_timeout(), 'runId': request['runId']}
                return {'status': 'Failed', 'runId': request['runId'], 'trainingObservation': None, 'error': 'synthetic'}
            return {**success(None), 'runId': request['runId']}
    game = FakeGame()
    monkeypatch.setattr(worker, 'GameProcess', lambda **kwargs: game)
    catalog = SimpleNamespace(config={'short_search_budget_ms': 8000, 'search_dop': 1,
        'battle_timeout_seconds': 120, 'native_failure_policy': POLICY},
        validate=lambda b: None, targets=lambda b: [{'id': 'SYNTHETIC_TARGET'}])
    assert worker.work(queue, catalog, runtime, 8)
    assert queue.counts() == {'complete': 1, 'quarantined': 1}
    assert [r['seed'] for r in game.requests] == ['bad', 'bad', 'bad', 'good']
    assert len({r['runId'] for r in game.requests}) == 4 and game.stops >= 4
    assert len(list((tmp_path / 'evidence').rglob('failure.json'))) == 3
