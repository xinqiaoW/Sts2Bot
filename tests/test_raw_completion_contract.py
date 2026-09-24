import copy
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'experiments/standalone-simulator'))
from run_probe import raw_completion_matches_execution


def completion():
    fixture = json.loads((ROOT / 'experiments/standalone-simulator/fixtures/restore-1.json').read_text())
    expected = fixture['expected']
    observation = copy.deepcopy(expected)
    hp = 27
    assert expected['finalHp'] != hp
    observation.update(finalHp=hp, netHpLoss=observation['initialHp'] - hp, playerDied=False)
    value = dict(status='StandaloneCompleted', combatEnded=True, runId=fixture['request']['runId'],
                 collectionRequest=copy.deepcopy(fixture['request']), trainingObservation=observation,
                 execution=dict(status='teacher_battle_completed', finalHp=hp, outcome='win', roomCompleted=True),
                 finishedTurn=10, finishedAtUtc='2026-09-24T00:00:00+00:00',
                 provenance=dict(backend='standalone-managed-native'), productionReady=False, productionLabels=False)
    return value, expected, fixture['request']


def test_different_search_route_is_checked_against_its_actual_execution():
    value, expected, request = completion()
    assert raw_completion_matches_execution(value, expected, request)


@pytest.mark.parametrize('mutation', ['label', 'net_loss', 'death', 'input', 'initial_build', 'unfinished', 'turn', 'time'])
def test_inconsistent_execution_label_or_request_is_rejected(mutation):
    value, expected, request = completion()
    if mutation == 'label': value['trainingObservation']['finalHp'] += 1
    elif mutation == 'net_loss': value['trainingObservation']['netHpLoss'] += 1
    elif mutation == 'death': value['trainingObservation']['playerDied'] = True
    elif mutation == 'input': value['collectionRequest']['seed'] = 'WRONG'
    elif mutation == 'initial_build': value['trainingObservation']['initialBuild']['cards'].pop()
    elif mutation == 'unfinished': value['combatEnded'] = False
    elif mutation == 'turn': value['finishedTurn'] = 0
    else: value['finishedAtUtc'] = 'not-a-time'
    assert not raw_completion_matches_execution(value, expected, request)
