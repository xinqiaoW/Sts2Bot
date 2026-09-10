"""Synthetic histories exercise chronology; these fixtures never enter collection."""
from collections import Counter
from copy import deepcopy
from dataclasses import replace
import gzip
import json
from pathlib import Path
import pytest

from damage_model.catalog import Catalog
from damage_model.run_import import (HistoryCard, apply_floor, build_for, import_run,
                                     reconstruct, RunRejected)
from damage_model.run_source import decode_page, retry_delay, sync_page
from damage_model.store import Store
from damage_model.worker import request_for

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def catalog():
    return Catalog.load(ROOT/'catalogs/game-0.111.0.raw.json', ROOT/'configs/real-runs.json')


def node(model, **changes):
    return {'rooms':[{'model_id':model}], 'player_stats':[{'player_id':1, 'max_hp':70, **changes}]}


@pytest.fixture
def run(catalog):
    deck = [{'id':'CARD.'+c, 'floor_added_to_deck':1} for c in
            (*catalog.raw['character']['starting_deck'], 'ASCENDERS_BANE')]
    next(c for c in deck if c['id']=='CARD.NEUTRALIZE')['current_upgrade_level'] = 1
    deck += [{'id':'CARD.BACKFLIP', 'floor_added_to_deck':2}]
    target = catalog.acts['OVERGROWTH']['encounters'][0]['id']
    return {'schema_version':10, 'build_id':'v0.111.0', 'ascension':10,
        'game_mode':'standard', 'modifiers':[], 'acts':['ACT.OVERGROWTH'],
        'players':[{'id':1, 'character':'CHARACTER.SILENT', 'deck':deck,
            'relics':[{'id':'RELIC.RING_OF_THE_SNAKE'}, {'id':'RELIC.POMANDER'}]}],
        'map_point_history':[[node('EVENT.NEOW',
            ancient_choice=[{'TextKey':'POMANDER','was_chosen':True}],
            relic_choices=[{'choice':'RELIC.POMANDER','was_picked':True}],
            upgraded_cards=['CARD.NEUTRALIZE']),
            node('ENCOUNTER.'+target, cards_gained=[{'id':'CARD.BACKFLIP'}]),
            node('ENCOUNTER.'+target)]]}


def test_precombat_reward_boundary_final_validation_and_curse(run, catalog):
    states = reconstruct(run, catalog)
    assert len(states[1]['cards']) == 13
    assert len(states[2]['cards']) == 14
    assert ('NEUTRALIZE',1,'{}') in states[1]['cards']
    assert ('ASCENDERS_BANE',0,'{}') in states[1]['cards']
    assert states[1]['ancient_history'] == ((1,'NEOW','POMANDER'),)
    broken = deepcopy(run)
    broken['players'][0]['deck'].pop()
    with pytest.raises(RunRejected, match='final deck'):
        reconstruct(broken, catalog)


def test_duplicate_upgrades_and_transform_not_double_counted(catalog):
    deck = (HistoryCard('STRIKE_SILENT',0,1),)*2
    result = apply_floor(deck, {'upgraded_cards':['CARD.STRIKE_SILENT']*2}, 2, catalog)
    assert result == {(HistoryCard('STRIKE_SILENT',1,1),)*2}
    transform = {'original_card':{'id':'CARD.STRIKE_SILENT','floor_added_to_deck':1},
                 'final_card':{'id':'CARD.BACKFLIP','floor_added_to_deck':2}}
    result = apply_floor(deck, {'cards_transformed':[transform]}, 2, catalog)
    assert result == {(HistoryCard('BACKFLIP',0,2),HistoryCard('STRIKE_SILENT',0,1))}


def test_ambiguous_card_instances_are_not_guessed(catalog):
    deck = (HistoryCard('BACKFLIP',0,1), HistoryCard('BACKFLIP',0,2))
    result = apply_floor(deck, {'upgraded_cards':['CARD.BACKFLIP']}, 3, catalog)
    assert len(result) == 2
    removed = {'id':'CARD.BACKFLIP','floor_added_to_deck':1,'current_upgrade_level':1}
    compatible = {d for candidate in result for d in apply_floor(candidate, {'cards_removed':[removed]}, 4, catalog)}
    assert compatible == {(HistoryCard('BACKFLIP',0,2),)}


def test_real_inventory_random_counters_are_reproducible_and_fixed_per_panel(run,catalog,tmp_path):
    snapshot = reconstruct(run,catalog)[1]
    snapshot['relics'] += ('PEN_NIB','TUNING_FORK')
    first, seed = build_for(snapshot,'run-a',catalog)
    second, seed2 = build_for(snapshot,'run-b',catalog)
    assert first.id == second.id and seed == seed2
    assert first.cards == second.cards
    assert 0 <= dict(first.relics[-1].state)['SkillsPlayed'] < 10
    store = Store(tmp_path/'jobs.sqlite')
    store.schedule(first,catalog.targets(first)[:1],['one','two'],{'fixture':True})
    a,b = store.claim(),store.claim()
    ra,rb = request_for(a,catalog.config),request_for(b,catalog.config)
    assert ra['relics'] == rb['relics'] and ra['seed'] != rb['seed']
    assert all(r['addWithoutObtainedEffects'] for r in ra['relics'])
    assert len(ra['runCards']) == 13 and ra['potionPolicyForTest']=='Disabled'


def test_import_is_idempotent_preserves_origin_and_never_uses_human_loss(run,catalog,tmp_path):
    run['map_point_history'][0][1]['player_stats'][0]['damage_taken'] = 123456
    store = Store(tmp_path/'jobs.sqlite')
    report = import_run(store,catalog,{'fixture':True},run,'aa','fixture')
    assert report['accepted_floors'] == 2
    assert store.counts() == {'pending':report['scheduled_now']}
    assert import_run(store,catalog,{'fixture':True},run,'aa','fixture')['scheduled_now'] == 0
    assert import_run(store,catalog,{'fixture':True},run,'bb','fixture')['scheduled_now'] == 0
    exported = {**run, 'run_hash':'aa', 'username':'presentation-only'}
    assert import_run(store,catalog,{'fixture':True},exported,'aa','fixture')['scheduled_now'] == 0
    assert store.db.execute('SELECT count(*) FROM build_origins').fetchone()[0] == 4
    assert not list(store.rows())
    run['ascension'] = 9
    with pytest.raises(ValueError, match='Source content'):
        import_run(store,catalog,{'fixture':True},run,'aa','fixture')


def test_unsupported_effects_keep_the_entire_build_out(run,catalog):
    state = reconstruct(run,catalog)[1]
    for rid in ('LIZARD_TAIL','PRISMATIC_GEM'):
        bad = {**state,'relics':state['relics']+(rid,)}
        with pytest.raises(ValueError, match='Disallowed relic|Ancient relic without acquisition history'):
            build_for(bad,'aa',catalog)
    state['cards'] += (('BACKFLIP',0,'{"props":{"ints":[{"name":"Unknown","value":1}]}}'),)
    with pytest.raises(RunRejected, match='persistent'):
        build_for(state,'aa',catalog)


def test_shared_export_metadata_compatibility_preserves_legacy_source_and_jobs(run,catalog,tmp_path):
    from damage_model.run_import import source_checksum
    shared = {**deepcopy(run),'is_beta':True,'damage':{'damage_taken':9999}}
    store=Store(tmp_path/'source.sqlite')
    import_run(store,catalog,{},shared,'aa','shared-endpoint')
    with store.db:
        store.db.execute('UPDATE source_runs SET sha256=? WHERE hash=?',
                         (source_checksum(shared,legacy=True),'aa'))
    original=tuple(store.db.execute('SELECT * FROM source_runs').fetchone())
    jobs=list(map(tuple,store.db.execute('SELECT * FROM jobs ORDER BY id')))
    exported={**deepcopy(run),'run_hash':'aa','_spirecodex_damage':{'damage_taken':8888}}
    for _ in range(2):
        result=import_run(store,catalog,{},exported,'aa','export-endpoint')
        assert result['already_imported'] and result['scheduled_now']==0
    assert tuple(store.db.execute('SELECT * FROM source_runs').fetchone())==original
    assert list(map(tuple,store.db.execute('SELECT * FROM jobs ORDER BY id')))==jobs
    variants=store.db.execute('SELECT body,policy FROM source_equivalences').fetchall()
    assert len(variants)==1 and json.loads(variants[0]['body'])==exported
    assert variants[0]['policy']=='spire_codex_metadata_v2'
    with store.db:store.db.execute("UPDATE source_runs SET sha256='invalid'")
    with pytest.raises(ValueError,match='Stored source checksum'):
        import_run(store,catalog,{},exported,'aa','export-endpoint')


@pytest.mark.parametrize('field', ['build_id','seed','history','nested_metadata','unknown_root'])
def test_api_metadata_normalization_never_hides_gameplay_changes(run,catalog,tmp_path,field):
    store=Store(tmp_path/'source.sqlite');import_run(store,catalog,{},run,'aa','fixture')
    changed={**deepcopy(run),'is_beta':True,'_spirecodex_damage':{'damage_taken':0}}
    if field=='build_id':changed['build_id']='v0.112.0'
    elif field=='seed':changed['seed']='different-seed'
    elif field=='history':changed['map_point_history'][0][1]['player_stats'][0]['damage_taken']=1
    elif field=='nested_metadata':changed['players'][0]['is_beta']=True
    else:changed['unreviewed_metadata']=1
    with pytest.raises(ValueError,match='Source content'):
        import_run(store,catalog,{},changed,'aa','export-endpoint')
    assert store.db.execute('SELECT count(*) FROM source_equivalences').fetchone()[0]==0


def test_gzip_truncation_never_becomes_a_partial_source_page():
    encoded = gzip.compress(b'{"run_hash":"aa"}\n')
    assert decode_page(encoded) == [{'run_hash':'aa'}]
    with pytest.raises((EOFError, gzip.BadGzipFile)):
        decode_page(encoded[:-8])
    assert retry_delay('120',0) == 120


def test_shared_builds_join_source_runs_in_one_training_family(run,catalog,tmp_path):
    from damage_model.run_import import source_groups
    store = Store(tmp_path/'jobs.sqlite')
    for source in ('aa','bb'):
        import_run(store,catalog,{'fixture':True},run,source,'fixture')
    families = source_groups(store.db)
    assert len(families) == 2 and len(set(families.values())) == 1


def test_cursor_moves_only_after_full_import_and_resumes_cached_page(run,catalog,tmp_path,monkeypatch):
    from damage_model import run_source
    from io import BytesIO
    run['run_hash'] = 'aa'
    class Response(BytesIO):
        headers = {'X-Next-Cursor':'next-page'}
    requested = []
    def fetch(request,timeout):
        requested.append(request.full_url)
        return Response(gzip.compress((json.dumps(run)+'\n').encode()))
    monkeypatch.setattr(run_source,'urlopen',fetch)
    monkeypatch.setattr(run_source.time,'time',lambda:100)
    real_import = run_source.import_run
    monkeypatch.setattr(run_source,'import_run',lambda *a: (_ for _ in ()).throw(RuntimeError('interrupted')))
    store = Store(tmp_path/'jobs.sqlite'); cache = tmp_path/'source'
    with pytest.raises(RuntimeError,match='interrupted'):
        sync_page(store,catalog,{'fixture':True},cache,'2026-09-01T00:00:00Z')
    assert json.loads((cache/'cursor.json').read_text())['cursor'] is None
    monkeypatch.setattr(run_source,'import_run',real_import)
    monkeypatch.setattr(run_source.time,'time',lambda:132)
    report = sync_page(store,catalog,{'fixture':True},cache,'2026-09-01T00:00:00Z')
    assert report['matching_runs'] == 1 and len(requested)==1
    assert json.loads((cache/'cursor.json').read_text())['cursor']=='next-page'


def test_history_overlap_preserves_completed_label_and_original_attempt(run,catalog,tmp_path,monkeypatch):
    from damage_model import run_source
    from io import BytesIO
    run['run_hash']='aa'
    store=Store(tmp_path/'jobs.sqlite')
    import_run(store,catalog,{'fixture':True},run,'aa','first-source')
    jid=store.db.execute('SELECT id FROM jobs LIMIT 1').fetchone()[0]
    with store.db:
        store.db.execute("UPDATE jobs SET status='complete',attempts=1,result=? WHERE id=?",('preserved-label',jid))
        store.db.execute("INSERT INTO attempts(job_id,status,result,finished) VALUES(?,'complete','preserved-attempt',1)",(jid,))
    before_jobs=[tuple(r) for r in store.db.execute('SELECT * FROM jobs ORDER BY id')]
    before_attempts=[tuple(r) for r in store.db.execute('SELECT * FROM attempts ORDER BY id')]
    class Response(BytesIO):
        headers={}
    monkeypatch.setattr(run_source,'urlopen',lambda *a,**kw:Response(gzip.compress((json.dumps(run)+'\n').encode())))
    report=sync_page(store,catalog,{'fixture':True},tmp_path/'history',None,follow=False)
    assert report['matching_runs']==1 and report['scheduled_now']==0
    assert [tuple(r) for r in store.db.execute('SELECT * FROM jobs ORDER BY id')]==before_jobs
    assert [tuple(r) for r in store.db.execute('SELECT * FROM attempts ORDER BY id')]==before_attempts
