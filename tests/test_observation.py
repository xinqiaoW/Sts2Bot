"""Synthetic boundary cases; real failure evidence is checked separately."""
import gzip
import json

import pytest

from damage_model.observation import validate_hp
from damage_model.schema import Build, Card, Relic
from damage_model.store import Store
from tools.export_snapshot import export_snapshot


SCROLL = {'id': 'SCROLLS_OF_BITING_WEAK', 'monsters': ['SCROLL_OF_BITING'], 'room_type': 'Monster'}


def obs(final_hp=62, final_max=66):
    return dict(initialHp=70, initialMaxHp=70, finalHp=final_hp,
                finalMaxHp=final_max, netHpLoss=70-final_hp, playerDied=final_hp == 0)


@pytest.mark.parametrize('target_id', ['SCROLLS_OF_BITING_NORMAL', 'SCROLLS_OF_BITING_WEAK'])
@pytest.mark.parametrize('hp,max_hp', [(62, 66), (54, 64), (0, 2), (0, 1), (1, 1), (70, 70)])
def test_paper_cuts_keeps_actual_hp_loss(target_id, hp, max_hp):
    validate_hp(obs(hp, max_hp), {**SCROLL, 'id': target_id})


@pytest.mark.parametrize('change', [
    {'finalMaxHp': 72}, {'finalMaxHp': 65}, {'finalMaxHp': 0},
    {'finalHp': 67}, {'netHpLoss': 4}, {'initialHp': 68},
    {'finalMaxHp': 66.0}, {'playerDied': True},
])
def test_other_corruption_is_still_rejected(change):
    with pytest.raises(ValueError):
        validate_hp({**obs(), **change}, SCROLL)


@pytest.mark.parametrize('target', [
    {'id': 'OTHER', 'monsters': ['SCROLL_OF_BITING']},
    {**SCROLL, 'monsters': ['OTHER']},
])
def test_no_general_max_hp_exception(target):
    with pytest.raises(ValueError):
        validate_hp(obs(), target)


@pytest.mark.parametrize('hp,max_hp', [(68, 68), (38, 66), (0, 2), (1, 1), (70, 70)])
@pytest.mark.parametrize('upgrade', [0, 1])
def test_brightest_flame_keeps_actual_hp_loss(hp, max_hp, upgrade):
    validate_hp({**obs(hp, max_hp), 'initialBuild': {'cards': [
        {'id': 'BRIGHTEST_FLAME', 'upgradeLevel': upgrade}]}}, {'id': 'BOWLBUGS_WEAK'})


@pytest.mark.parametrize('change', [{'finalMaxHp': 72}, {'finalMaxHp': 65},
                                  {'finalHp': 69}, {'netHpLoss': 0}])
def test_brightest_flame_does_not_allow_unrelated_corruption(change):
    with pytest.raises(ValueError):
        validate_hp({**obs(68, 68), 'initialBuild': {'cards': [
            {'id': 'BRIGHTEST_FLAME', 'upgradeLevel': 0}]}, **change}, {'id': 'BOWLBUGS_WEAK'})


def test_store_and_export_preserve_final_max_hp(tmp_path):
    store = Store(tmp_path/'test.sqlite')
    build = Build('GLORY', 3, (Card('STRIKE_SILENT'),),
                  (Relic('RING_OF_THE_SNAKE'),), (), 'synthetic-fixture')
    store.schedule(build, [SCROLL], ['seed'], {'test_fixture': True})
    job = store.claim()
    result = dict(status='Passed', combatEnded=True, runId='synthetic', finishedTurn=2,
                  elapsedMilliseconds=100, finishedAtUtc='2026-09-06T00:00:00Z',
                  trainingObservation={**obs(), 'complete': True, 'initialBuild': {
                      'character': 'SILENT', 'ascension': 10, 'actId': 'GLORY',
                      'cards': [{'id': 'STRIKE_SILENT', 'upgradeLevel': 0}],
                      'relics': [{'id': 'RING_OF_THE_SNAKE', 'counters': {}}]}})
    assert store.finish(job, result) == 'complete'
    output = tmp_path/'export.json.gz'
    export_snapshot(tmp_path/'test.sqlite', output)
    with gzip.open(output, 'rt', encoding='utf-8') as stream:
        battle = json.load(stream)['battles'][0]
    assert (battle['initial_hp'], battle['max_hp'], battle['final_hp'], battle['final_max_hp'], battle['hp_loss']) == (70, 70, 62, 66, 8)

    # Current scope must stay separate from preserved historical labels.
    store.db.execute('INSERT INTO collection_settings VALUES(?,?)',
                     ('target_policy', json.dumps({'name': 'source_floor_window_v1', 'radius': 2, 'same_act': True})))
    store.db.execute('INSERT INTO target_origins VALUES(?,?,?,?,?)',
                     (build.id, 'synthetic-source', 10, 11, 'SELECTED_TARGET'))
    store.db.commit()
    export_snapshot(tmp_path/'test.sqlite', output)
    with gzip.open(output, 'rt', encoding='utf-8') as stream:
        exported = json.load(stream)
    assert exported['selected_targets'] == {build.id: ['SELECTED_TARGET']}
    assert exported['battles'][0]['target_id'] == SCROLL['id']
