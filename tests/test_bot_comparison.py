import json
from pathlib import Path

import pytest

from runctl.batch import summarize
from runctl.compare import compare_experiments


def report(root, name, outcomes, revision='frozen'):
    directory = root/name
    directory.mkdir()
    episodes = [dict(seed=f'S{i}', runId=f'{name}-{i}', outcome=outcome,
                     state=dict(floor=50 if outcome=='victory' else 20, act=3 if outcome=='victory' else 2))
                for i, outcome in enumerate(outcomes)]
    summary = summarize([dict(index=0, returncode=0, episodes=episodes)], len(episodes))
    (directory/'summary.json').write_text(json.dumps(summary))
    (directory/'experiment.json').write_text(json.dumps(dict(source_revision=revision)))
    return directory


def test_selection_and_paired_win_disagreements(tmp_path):
    a = report(tmp_path, 'A', ['victory', 'death', 'victory'])
    b = report(tmp_path, 'B', ['death', 'victory', 'death'])
    result = compare_experiments(dict(A=a, B=b))
    assert result['selected'] == 'A' and result['tuning_games'] == 6
    assert result['paired_comparisons'] == [dict(selected='A', other='B', selected_only_wins=2, other_only_wins=1)]


def test_incomplete_experiment_cannot_win_selection(tmp_path):
    a = report(tmp_path, 'A', ['victory'])
    p = a/'summary.json'; s = json.loads(p.read_text()); s['requested'] = 2; p.write_text(json.dumps(s))
    with pytest.raises(ValueError, match='incomplete'): compare_experiments(dict(A=a))


@pytest.mark.parametrize('mismatch', ['seeds', 'revision'])
def test_incompatible_experiments_are_not_paired(tmp_path, mismatch):
    a = report(tmp_path, 'A', ['victory'])
    b = report(tmp_path, 'B', ['death'], revision='changed' if mismatch=='revision' else 'frozen')
    if mismatch=='seeds':
        p=b/'summary.json';s=json.loads(p.read_text());s['workers'][0]['episodes'][0]['seed']='OTHER';p.write_text(json.dumps(s))
    with pytest.raises(ValueError): compare_experiments(dict(A=a, B=b))
