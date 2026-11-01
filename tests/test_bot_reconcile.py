import json
import pytest

from runctl.reconcile import reconcile


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))


@pytest.fixture
def attempts(tmp_path):
    source, retry = tmp_path / 'source', tmp_path / 'retry'
    failure = dict(seed='same-seed', runId='failed', error='Wine startup fault')
    write(source / 'summary.json', dict(requested=1, failed_workers=1, workers=[
        dict(index=0, requested=1, returncode=1, episodes=[], failure=failure)]))
    write(source / 'experiment.json', dict(source_revision='frozen'))
    write(source / 'worker-00/policy-config.json', dict(margin=1))
    write(retry / 'policy-config.json', dict(margin=1))
    write(retry / 'retry-provenance.json', dict(source_revision='frozen', failed_run_id='failed'))
    write(retry / 'summary.json', dict(completed=1, episodes=[dict(seed='same-seed', runId='retried',
        status='complete', outcome='death', state=dict(floor=11, act=1))]))
    return source, retry


def test_retry_is_a_recorded_real_result_not_an_extra_loss(attempts):
    source, retry = attempts
    summary, manifest = reconcile(source, {0: retry})
    assert summary['completed'] == summary['deaths'] == 1
    assert summary['failed_attempts'] == 1 and summary['failed_workers'] == 0
    assert summary['retries'][0]['original_failure']['runId'] == 'failed'
    assert manifest['original_experiment'] == str(source)
    assert json.loads((source / 'summary.json').read_text())['failed_workers'] == 1


@pytest.mark.parametrize('change', ['seed', 'config', 'revision', 'incomplete'])
def test_retry_cannot_change_experiment_or_hide_incomplete_slots(attempts, change):
    source, retry = attempts
    if change == 'seed':
        path = retry / 'summary.json'
        data = json.loads(path.read_text()); data['episodes'][0]['seed'] = 'replacement-seed'
    elif change == 'config':
        path = retry / 'policy-config.json'; data = dict(margin=0)
    elif change == 'revision':
        path = retry / 'retry-provenance.json'; data = dict(source_revision='new', failed_run_id='failed')
    else:
        path = source / 'summary.json'
        data = json.loads(path.read_text()); data['requested'] = 2
    write(path, data)
    with pytest.raises(ValueError): reconcile(source, {0: retry})
