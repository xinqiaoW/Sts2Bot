import pytest
from damage_model.schema import Build, Card, Relic
from damage_model.store import Store


def prepare_store(tmp_path, native=False):
    store = Store(tmp_path / 'isolated.sqlite')
    teacher = {'collector_protocol': 3, 'game_sha256': 'a' * 64, 'collector_sha256': 'b' * 64}
    if not native:
        teacher.update(execution_backend='standalone-managed-native', validation_scope='isolated-experiment',
                       standalone_host_sha256='c' * 64, standalone_unlock_state='all')
    build = Build('OVERGROWTH', 1, (Card('GUILTY', persistent_state={'CombatsSeen': 1}),),
                  (Relic('RING_OF_THE_SNAKE'),), (), 'fixture')
    store.schedule(build, [{'id': 'BYGONE_EFFIGY_ELITE'}], ['seed'], teacher)
    job = store.claim()
    result = {'status': 'StandaloneCompleted', 'combatEnded': True, 'runId': 'run-1',
              'productionReady': False, 'productionLabels': False,
              'collectionRequest': {'runId': 'run-1', 'seed': 'seed', 'encounterId': 'BYGONE_EFFIGY_ELITE'},
              'provenance': {'backend': 'standalone-managed-native', 'collectorProtocol': 3,
                             'gameSha256': 'a' * 64, 'solverSha256': 'b' * 64, 'hostSha256': 'c' * 64,
                             'testMode': True, 'unlockState': 'all', 'productionValidated': False},
              'trainingObservation': {'complete': True, 'initialHp': 70, 'initialMaxHp': 70,
                 'finalHp': 30, 'finalMaxHp': 70, 'netHpLoss': 40, 'playerDied': False,
                 'initialBuild': {'character': 'SILENT', 'ascension': 10, 'actId': 'OVERGROWTH',
                    'cards': [{'id': 'GUILTY', 'upgradeLevel': 0, 'persistentState': {'CombatsSeen': 1}}],
                    'relics': [{'id': 'RING_OF_THE_SNAKE', 'counters': {}}]}}}
    return store, job, result


def test_isolated_submission_preserves_status_and_rejects_duplicate_lease(tmp_path):
    store, job, result = prepare_store(tmp_path)
    assert store.finish(job, result) == 'complete'
    stored = store.db.execute('SELECT result FROM attempts').fetchone()[0]
    assert 'StandaloneCompleted' in stored and '"Passed"' not in stored
    with pytest.raises(ValueError, match='Stale'):
        store.finish(job, result)
    assert store.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 1


@pytest.mark.parametrize('change', ['hash', 'scope', 'seed', 'target', 'run_id', 'protocol', 'native_status', 'hp', 'card'])
def test_mismatched_evidence_cannot_complete_job(tmp_path, change):
    store, job, result = prepare_store(tmp_path)
    if change == 'hash': result['provenance']['hostSha256'] = 'd' * 64
    if change == 'scope': job['teacher']['validation_scope'] = 'production'
    if change == 'seed': result['collectionRequest']['seed'] = 'different'
    if change == 'target': result['collectionRequest']['encounterId'] = 'different'
    if change == 'run_id': result['runId'] = 'different'
    if change == 'protocol': result['provenance']['collectorProtocol'] = 2
    if change == 'native_status': result['status'] = 'Passed'
    if change == 'hp': result['trainingObservation']['netHpLoss'] = 0
    if change == 'card': result['trainingObservation']['initialBuild']['cards'][0]['persistentState']['CombatsSeen'] = 2
    with pytest.raises(ValueError): store.finish(job, result)
    assert store.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
    assert store.finish(job, {'status': 'InvalidObservation', 'error': change}) == 'failed'
    assert store.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 1


def test_native_and_standalone_teacher_cannot_mix(tmp_path):
    store, job, result = prepare_store(tmp_path, native=True)
    with pytest.raises(ValueError, match='native teacher'): store.finish(job, result)
    result['status'] = 'Passed'
    with pytest.raises(ValueError, match='native teacher'): store.finish(job, result)
    result.pop('provenance')
    assert store.finish(job, result) == 'complete'


def test_standalone_timeout_is_recorded_as_failure_without_label(tmp_path):
    store, job, _ = prepare_store(tmp_path)
    assert store.finish(job, {'status': 'StandaloneTimeout', 'error': 'hard deadline'}) == 'failed'
    assert store.db.execute("SELECT count(*) FROM jobs WHERE status='complete'").fetchone()[0] == 0


@pytest.mark.parametrize('matching', [True, False])
def test_progress_snapshot_identity_is_required(tmp_path, matching):
    store, job, result = prepare_store(tmp_path)
    job['teacher'].update(standalone_unlock_state='progress-snapshot', progress_snapshot_sha256='d' * 64)
    result['provenance'].update(unlockState='progress-snapshot', progressSnapshotSha256=('d' if matching else 'e') * 64)
    from damage_model.provenance import completed_by_expected_backend
    if matching:
        assert completed_by_expected_backend(job, result)
    else:
        with pytest.raises(ValueError, match='progress snapshot'):
            completed_by_expected_backend(job, result)
