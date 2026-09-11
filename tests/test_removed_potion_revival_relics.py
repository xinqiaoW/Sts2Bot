"""Removed relics must rescue source builds without changing existing labels."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path

import pytest

from damage_model import run_import
from damage_model.catalog import Catalog
from damage_model.run_import import build_for, import_run, reconstruct
from damage_model.schema import Relic
from damage_model.store import Store
from damage_model.worker import request_for
from test_pipeline import observation
from test_run_import import catalog, run

REMOVED = {'PHIAL_HOLSTER', 'PETRIFIED_TOAD', 'LIZARD_TAIL'}
ROOT = Path(__file__).resolve().parents[1]


def with_relic(source, rid):
    source = deepcopy(source)
    if rid == 'PHIAL_HOLSTER':
        stats = source['map_point_history'][0][0]['player_stats'][0]
        stats['ancient_choice'][0]['TextKey'] = rid
        stats['relic_choices'][0]['choice'] = 'RELIC.' + rid
        source['players'][0]['relics'][1]['id'] = 'RELIC.' + rid
    else:
        source['map_point_history'][0][1]['player_stats'][0]['relic_choices'] = [
            {'choice': 'RELIC.' + rid, 'was_picked': True}]
        source['players'][0]['relics'].append({'id': 'RELIC.' + rid})
    return source


@pytest.mark.parametrize('config_name', ['real-runs.json', 'real-runs-8s.json'])
def test_both_real_configs_remove_all_three(catalog, config_name):
    config = json.loads((ROOT / 'configs' / config_name).read_text())
    checked = Catalog(catalog.raw, config)
    assert REMOVED <= checked.normalized_relic_ids
    assert not REMOVED & set(checked.relic_pool)
    assert not REMOVED & set(config['excluded_relic_ids'])
    assert config['short_search_budget_ms'] == (8000 if '8s' in config_name else 2000)


@pytest.mark.parametrize('rid', sorted(REMOVED))
def test_normalization_preserves_cards_order_counters_and_provenance(run, catalog, rid):
    state = reconstruct(with_relic(run, rid), catalog)[-1]
    # Pick a catalog enchantment so this checks exact persistence, not a guessed ID.
    enchantment = next(iter(catalog.enchantments))
    state['cards'] += (('DEFEND_SILENT', 1,
        json.dumps({'enchantment': {'id': 'ENCHANTMENT.' + enchantment, 'amount': 1}})),)
    state['relics'] += ('PEN_NIB', 'PETRIFIED_TOAD' if rid != 'PETRIFIED_TOAD' else 'LIZARD_TAIL')
    normalized, seed = build_for(state, 'source-a', catalog)
    repeat, repeated_seed = build_for(state, 'source-b', catalog)
    assert normalized.id == repeat.id and seed == repeated_seed
    assert [r.id for r in normalized.relics] == [r for r in state['relics'] if r not in REMOVED]
    assert normalized.ancient_history == state['ancient_history']
    assert [(c.id, c.upgrade) for c in normalized.cards] == [(c, u) for c, u, _ in state['cards']]
    assert normalized.cards[-1].enchantment_id == enchantment
    assert normalized.cards[-1].enchantment_amount == 1
    assert dict(normalized.relics[-1].state).keys() == {'AttacksPlayed'}
    request = request_for({'id': 'fixture', 'build': normalized.to_dict(), 'seed': 'one',
                           'target': catalog.targets(normalized)[0]}, catalog.config)
    assert not REMOVED & {r['relicId'] for r in request['relics']}
    assert request['potions'] == [] and request['potionPolicyForTest'] == 'Disabled'
    with pytest.raises(ValueError, match='Disallowed relic'):
        catalog.validate(replace(normalized, relics=normalized.relics + (Relic(rid),)))
    if rid == 'PHIAL_HOLSTER':
        missing = {**state, 'relics': tuple(r for r in state['relics'] if r != rid)}
        with pytest.raises(ValueError, match='ancient provenance'):
            build_for(missing, 'bad-source', catalog)


@pytest.mark.parametrize('rid', sorted(REMOVED))
@pytest.mark.parametrize('revision', [run_import.PREVIOUS_IMPORT_REVISION, run_import.SHARED_ANCIENT_REVISION])
def test_reaudit_adds_missing_jobs_preserves_source_labels_and_old_report(run, catalog, tmp_path, monkeypatch, rid, revision):
    old = Catalog(catalog.raw, {**catalog.config,
        'removed_relic_ids': sorted(set(catalog.config['removed_relic_ids']) - REMOVED),
        'excluded_relic_ids': catalog.config['excluded_relic_ids'] + ['LIZARD_TAIL']})
    store = Store(tmp_path / 'jobs.sqlite')
    source = with_relic(run, rid)
    with monkeypatch.context() as patch:
        patch.setattr(run_import, 'IMPORT_REVISION', revision)
        import_run(store, old, {}, run, 'baseline', 'fixture')
        previous = import_run(store, old, {}, source, 'source', 'original-url')
    assert previous['skipped']['Disallowed relic: ' + rid] > 0
    job = store.claim()
    assert store.finish(job, observation(job)) == 'complete'
    saved = tuple(store.db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone())
    attempts = [tuple(r) for r in store.db.execute('SELECT * FROM attempts')]
    original_source = tuple(store.db.execute('SELECT hash,sha256,source,body FROM source_runs WHERE hash=?', ('source',)).fetchone())
    revised = import_run(store, catalog, {}, source, 'source', 'new-url')
    assert revised['version'] == run_import.IMPORT_REVISION
    assert revised['accepted_floors'] == 2
    assert revised['removed_user_relics'][rid] > 0
    assert 'Disallowed relic: ' + rid not in revised['skipped']
    assert tuple(store.db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone()) == saved
    assert [tuple(r) for r in store.db.execute('SELECT * FROM attempts')] == attempts
    assert tuple(store.db.execute('SELECT hash,sha256,source,body FROM source_runs WHERE hash=?', ('source',)).fetchone()) == original_source
    history = store.db.execute('SELECT version,report FROM source_import_history WHERE hash=?', ('source',)).fetchone()
    assert history['version'] == revision and json.loads(history['report']) == previous
    assert import_run(store, catalog, {}, source, 'source', 'url')['scheduled_now'] == 0
    # An unaffected cached source stays byte-for-byte on its old revision.
    assert import_run(store, catalog, {}, run, 'baseline', 'url')['scheduled_now'] == 0
    assert store.db.execute('SELECT version FROM source_runs WHERE hash=?', ('baseline',)).fetchone()[0] == revision


def test_other_unsupported_relic_still_rejects_build(run, catalog):
    state = reconstruct(run, catalog)[-1]
    state['relics'] += ('PETRIFIED_TOAD', 'BURNING_BLOOD')
    with pytest.raises(ValueError, match='Disallowed relic: BURNING_BLOOD'):
        build_for(state, 'source', catalog)
