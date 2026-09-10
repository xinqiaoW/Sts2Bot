"""Synthetic fixtures here never enter a real collection database."""
from dataclasses import replace
import copy
import json
from pathlib import Path

import numpy as np
import pytest

from damage_model.catalog import Catalog, COUNTER_DOMAINS
from damage_model.schema import Build, Card, Relic
from damage_model.store import Store
from damage_model.worker import request_for

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def catalog():
    return Catalog.load(ROOT/'catalogs/game-0.111.0.raw.json', ROOT/'configs/v1.json')


@pytest.fixture
def build(catalog):
    relic = next(r for r in catalog.ancients['NEOW']['possible_relics'] if r in catalog.relic_pool and r not in COUNTER_DOMAINS)
    return Build('OVERGROWTH', 1, tuple(Card(c) for c in catalog.raw['character']['starting_deck']),
                 (Relic('RING_OF_THE_SNAKE'), Relic(relic)), ((1, 'NEOW', relic),), 'synthetic-fixture')


def observation(job, hp=53):
    b = job['build']
    return {'status':'Passed', 'combatEnded':True, 'trainingObservation':{
        'complete':True, 'initialHp':70, 'initialMaxHp':70,
        'finalHp':hp, 'finalMaxHp':70, 'netHpLoss':70-hp, 'playerDied':hp==0,
        'initialBuild':{'character':'SILENT', 'ascension':10, 'actId':b['act_id'],
            'cards':[{'id':c['id'], 'upgradeLevel':c['upgrade']} for c in b['cards']],
            'relics':[{'id':r['id'], 'counters':dict(r['state'])} for r in b['relics']]}}}


def queued(tmp_path, catalog, build, seeds=('a',)):
    store=Store(tmp_path/'test.sqlite')
    store.schedule(build,catalog.targets(build)[:1],seeds,{'test_fixture':True})
    return store


def test_excluded_relics_and_healing_policy(catalog):
    for relic in ('LIZARD_TAIL','PRISMATIC_GEM','MANGO','STRAWBERRY','DARKSTONE_PERIAPT'):
        assert relic not in catalog.relic_pool
    assert 'BLOOD_VIAL' in catalog.relic_pool


def test_reject_wrong_ancient_act_and_counter_type(catalog,build):
    with pytest.raises(ValueError): catalog.validate(replace(build,act=2))
    with pytest.raises(ValueError): catalog.validate(replace(build,ancient_history=()))
    with pytest.raises(ValueError):
        catalog.validate(replace(build,relics=build.relics+(Relic('PEN_NIB',(('AttacksPlayed',True),)),)))
    with pytest.raises(ValueError):
        catalog.validate(replace(build,cards=build.cards+(Card('BASH'),)))


def test_hash_deduplicates_deck_order_but_keeps_relic_state(build):
    assert replace(build,cards=tuple(reversed(build.cards))).id==build.id
    assert replace(build,family='elsewhere',generation=99).id==build.id
    a=replace(build,relics=build.relics+(Relic('PEN_NIB',(('AttacksPlayed',0),)),))
    b=replace(build,relics=build.relics+(Relic('PEN_NIB',(('AttacksPlayed',9),)),))
    assert a.id!=b.id


def test_completed_losses_and_deaths_are_both_retained(tmp_path,catalog,build):
    store=queued(tmp_path,catalog,build,('a','b'))
    for hp in (53,0):
        job=store.claim()
        assert store.finish(job,observation(job,hp))=='complete'
    observations = [r['result']['trainingObservation'] for r in store.rows()]
    assert sorted((o['netHpLoss'], o['playerDied']) for o in observations) == [(17, False), (70, True)]


@pytest.mark.parametrize('corrupt', ['healed_max','not_full','wrong_deck','wrong_counter','wrong_death','partial'])
def test_invalid_labels_do_not_train(tmp_path,catalog,build,corrupt):
    store=queued(tmp_path,catalog,build); job=store.claim(); result=observation(job)
    obs=result['trainingObservation']
    if corrupt=='healed_max': obs['finalMaxHp']=75
    elif corrupt=='not_full': obs['initialHp']=60
    elif corrupt=='wrong_deck': obs['initialBuild']['cards'].pop()
    elif corrupt=='wrong_counter': obs['initialBuild']['relics'][-1]['counters']={'fake':7}
    elif corrupt=='wrong_death': obs['playerDied']=True
    else:
        obs['complete']=False
        assert store.finish(job,result)=='failed'
        assert not list(store.rows())
        return
    with pytest.raises(ValueError): store.finish(job,result)
    assert not list(store.rows())


def test_leases_dedupe_teacher_and_lineage(tmp_path,catalog,build):
    store=queued(tmp_path,catalog,build)
    original=store.add_build(replace(build,family='different'))
    assert original.family==build.family
    old=store.claim()
    assert store.claim() is None
    store.db.execute('UPDATE jobs SET lease_until=0'); store.db.commit()
    fresh=store.claim()
    with pytest.raises(ValueError): store.finish(old,observation(old))
    assert store.finish(fresh,observation(fresh))=='complete'
    assert store.db.execute("SELECT COUNT(*) FROM attempts WHERE status='expired'").fetchone()[0]==1
    with pytest.raises(ValueError): store.schedule(build,catalog.targets(build),['c'],{'teacher':'different'})


def test_request_has_independent_native_start(tmp_path,catalog,build):
    store=queued(tmp_path,catalog,build); job=store.claim(); request=request_for(job,catalog.config)
    assert request['trainingCollection'] and request['clearRunDeck']
    assert request['ascension']==10 and request['potionPolicyForTest']=='Disabled'
    assert len(request['runCards'])==12 and request['cards']==[]
    assert 'initialHpForTest' not in request and 'enemyHp' not in request


def test_encoder_card_multiset_and_counter_distinction(catalog,build):
    pytest.importorskip('torch')
    from damage_model.model import Encoder, DamageNet
    import torch
    encoder=Encoder.from_catalog(catalog); target=catalog.targets(build)[0]['id']
    x=encoder.encode(build,target,70)
    np.testing.assert_array_equal(x,encoder.encode(replace(build,cards=tuple(reversed(build.cards))),target,70))
    b=replace(build,relics=build.relics+(Relic('PEN_NIB',(('AttacksPlayed',9),)),))
    assert not np.array_equal(x,encoder.encode(b,target,70))
    loss,death=DamageNet(len(x))(torch.from_numpy(x[None,:]))
    assert loss.shape==death.shape==(1,) and torch.isfinite(loss).all()


def test_training_refuses_insufficient_data(tmp_path,catalog,build):
    pytest.importorskip('torch')
    from damage_model.model import train
    store=queued(tmp_path,catalog,build); job=store.claim(); store.finish(job,observation(job))
    with pytest.raises(ValueError): train(store,catalog,tmp_path/'model',epochs=1)
    assert not (tmp_path/'model/model.pt').exists()


def test_train_save_reload_with_isolated_synthetic_data(tmp_path,catalog,build):
    pytest.importorskip('torch')
    from damage_model.model import train, predict
    from damage_model.checkpoint_validation import validate_checkpoint
    store=Store(tmp_path/'synthetic-only.sqlite')
    target=catalog.targets(build)[0]
    for i,card in enumerate(catalog.card_pool[:65]):
        b=replace(build,cards=build.cards+(Card(card),),family=f'synthetic-test-{i}')
        store.schedule(b,[target],['one','two'],{'synthetic_test_only':True})
    while (job:=store.claim()) is not None: store.finish(job,observation(job,40))
    metrics=train(store,catalog,tmp_path/'synthetic-model',epochs=2)
    assert set(metrics)=={'train','validation','test'}
    assert metrics['test']['pair_mean_mae_hp']>=0
    answer=predict(tmp_path/'synthetic-model/model.pt',build,target['id'],70)
    assert 0<=answer['expected_hp_loss']<=70 and 0<=answer['death_probability']<=1
    report=validate_checkpoint(store,catalog,tmp_path/'synthetic-model')
    assert report['validated'] and report['completed_samples']==130
    assert report['baselines']['test']['target_mean_pair_mae_hp']==0
    # Counts alone cannot detect a changed teacher; the artifact must match provenance too.
    store.db.execute('UPDATE jobs SET teacher=?', ('{"different_teacher":true}',)); store.db.commit()
    with pytest.raises(ValueError,match='teacher differs'):
        validate_checkpoint(store,catalog,tmp_path/'synthetic-model')


def test_runtime_hash_rejects_changed_teacher(tmp_path):
    from damage_model.provenance import verify_runtime, sha256
    paths={'game_sha256':'data_sts2_windows_x86_64/sts2.dll',
           'collector_sha256':'mods/CombatSolver/CombatSolver.dll',
           'ritsu_sha256':'mods/STS2-RitsuLib/STS2-RitsuLib.dll'}
    teacher={}
    for key,path in paths.items():
        p=tmp_path/path; p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(b'fixture')
        teacher[key]=sha256(p)
    verify_runtime({'game_dir':str(tmp_path)},teacher)
    (tmp_path/paths['collector_sha256']).write_bytes(b'changed')
    with pytest.raises(ValueError): verify_runtime({'game_dir':str(tmp_path)},teacher)


@pytest.mark.parametrize('command', ['seed','evolve'])
def test_removed_generator_commands_cannot_create_jobs(tmp_path, monkeypatch, command):
    from damage_model.cli import main
    import sys
    db = tmp_path/'must-not-exist.sqlite'
    monkeypatch.setattr(sys, 'argv', ['damage_model', '--db', str(db), command])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2 and not db.exists()


def test_concurrent_workers_do_not_duplicate_jobs(tmp_path,catalog,build):
    from concurrent.futures import ThreadPoolExecutor
    store=queued(tmp_path,catalog,build,tuple(f'parallel-{i}' for i in range(24)))
    def collect(_):
        connection=Store(tmp_path/'test.sqlite')
        try:
            job=connection.claim()
            assert connection.finish(job,observation(job))=='complete'
            return job['id']
        finally: connection.db.close()
    with ThreadPoolExecutor(max_workers=8) as pool: ids=list(pool.map(collect,range(24)))
    assert len(set(ids))==24 and store.counts()=={'complete':24}


def test_parallel_pool_rejects_shared_prefix(tmp_path):
    from tools.collect_parallel import validate_runtimes
    paths=[]
    for i in range(2):
        path=tmp_path/f'runtime-{i}.json'
        path.write_text(json.dumps({'data_dir':str(tmp_path/f'data-{i}'),
                                   'env':{'WINEPREFIX':str(tmp_path/'same-prefix')}}))
        paths.append(path)
    with pytest.raises(ValueError,match='prefix'): validate_runtimes(paths)


def test_graceful_stop_does_not_claim_another_battle(tmp_path,catalog,build):
    from damage_model.worker import work
    store=queued(tmp_path,catalog,build)
    data=tmp_path/'game-data';data.mkdir();(data/'collector.stop').touch()
    config=tmp_path/'runtime.json'
    config.write_text(json.dumps({'game_dir':str(tmp_path),'data_dir':str(data),'command':[]}))
    assert work(store,catalog,config,1)
    assert store.counts()=={'pending':1}


@pytest.mark.parametrize('reason',[
    'NativeStartupCacheFailure','NativeEnumCacheFailure','NativeWinePageFault','NativeMenuCleanupFailure','NativeFinalizerCleanupFailure','NativeFinalizerReuseFailure','NativeAssetLoadingFailure'])
def test_startup_retries_are_narrow_bounded_and_preserved(tmp_path,catalog,build,reason):
    from damage_model.worker import startup_cache_failure
    message='A concurrent update was performed on this collection and corrupted its state'
    assert not startup_cache_failure(message+'\nOtherDictionary.Get[T]()')
    assert startup_cache_failure(message+'\nMaxEnumValueCache.Get[T]()')
    store=queued(tmp_path,catalog,build)
    for index in range(3):
        job=store.claim()
        if index==0:
            with pytest.raises(ValueError): store.retry_startup(job,{'status':'Timeout'})
            with pytest.raises(ValueError): store.retry_startup(job,{'status':'ProcessExited'})
        status=store.retry_startup(job,{'status':reason})
        assert status==('retry' if index<2 else 'failed')
    assert store.db.execute('SELECT COUNT(*) FROM attempts').fetchone()[0]==3
    assert not list(store.rows())


def test_reused_process_cache_failure_is_retried_without_stale_log_detection(tmp_path):
    import sys
    from damage_model.worker import GameProcess
    data=tmp_path/'data';data.mkdir()
    script=tmp_path/'game.py'
    script.write_text('''import json,sys,time
from pathlib import Path
data=Path(sys.argv[1]);last=None
while True:
 p=data/'combat_solver_test_request.json'
 if p.exists():
  request=json.loads(p.read_text());run=request['runId']
  if run!=last:
   last=run
   if run=='second':
    print('MaxEnumValueCache.Get[T]()\\nA concurrent update was performed on this collection and corrupted its state',flush=True)
    while True: time.sleep(.1)
   for name,value in [('result',{'runId':run,'status':'Passed'}),('ready',{'schemaVersion':1,'runId':run,'held':False})]:
    dest=data/f'combat_solver_test_{name}.json';temp=dest.with_suffix('.tmp')
    temp.write_text(json.dumps(value));temp.replace(dest)
 time.sleep(.02)
''')
    game=GameProcess(tmp_path,data,[sys.executable,'-u',str(script),str(data)],log_path=tmp_path/'game.log')
    try:
        assert game.run({'runId':'first','timeoutSeconds':3})['status']=='Passed'
        first_pid=game.process.pid
        result=game.run({'runId':'second','timeoutSeconds':3})
        assert result['status']=='NativeEnumCacheFailure'
        assert game.process is None
        assert game.run({'runId':'third','timeoutSeconds':3})['status']=='Passed'
        assert game.process.pid!=first_pid
        assert game.run({'runId':'fourth','timeoutSeconds':3})['status']=='Passed'
    finally: game.stop()


MENU_CLEANUP_CRASH = '''[CombatSolver/Unattended] STAGE run_id=crash-check stage=cleanup elapsed_ms=8403.7
ERROR: FATAL: Index p_index = 7 is out of bounds (size() = 0).
   at: get (./core/templates/cowdata.h:187)
   MegaCrit.Sts2.Core.Nodes.Screens.Settings.NInputSettingsEntry.Create(string)
   MegaCrit.Sts2.Core.Nodes.NGame+<LoadMainMenu>d__144.MoveNext()
Fatal error. 0xC000001D'''


FINALIZER_CLEANUP_CRASH = '''[CombatSolver/Unattended] STAGE run_id=crash-check stage=cleanup elapsed_ms=11001.6
Fatal error. 0xC0000005
   at Godot.GodotObject.Dispose(Boolean)
   at Godot.GodotObject.Finalize()
   at System.GC.RunFinalizers()'''


FINALIZER_REUSE_CRASH = ('[CombatSolver/Unattended] REQUEST_ACCEPTED run_id=crash-check '
    'scenario=HP-test process_sequence=40 reused_process=True\n' +
    FINALIZER_CLEANUP_CRASH.replace('stage=cleanup', 'stage=wait_combat_end'))


@pytest.mark.parametrize('message,expected',[
    ('wine: Unhandled page fault on write access to 000000000000010C at address 0000000140A6F581 (thread 0990), starting debugger...','NativeWinePageFault'),
    ('Unexpected application exit without a recognized native crash','ProcessExited'),
    (MENU_CLEANUP_CRASH,'NativeMenuCleanupFailure'),
    (MENU_CLEANUP_CRASH.replace('run_id=crash-check','run_id=previous-request'),'ProcessExited'),
    (MENU_CLEANUP_CRASH.replace('stage=cleanup','stage=wait_combat_end'),'ProcessExited'),
    (MENU_CLEANUP_CRASH.replace('is out of bounds (size() = 0).','different native failure'),'ProcessExited'),
    (FINALIZER_CLEANUP_CRASH,'NativeFinalizerCleanupFailure'),
    (FINALIZER_CLEANUP_CRASH.replace('run_id=crash-check','run_id=previous-request'),'ProcessExited'),
    (FINALIZER_CLEANUP_CRASH.replace('stage=cleanup','stage=wait_combat_end'),'ProcessExited'),
    (FINALIZER_CLEANUP_CRASH.replace('at Godot.GodotObject.Finalize()','at OtherFinalizer()'),'ProcessExited'),
    (FINALIZER_REUSE_CRASH,'NativeFinalizerReuseFailure'),
    (FINALIZER_REUSE_CRASH.replace('reused_process=True','reused_process=False'),'ProcessExited'),
    (FINALIZER_REUSE_CRASH.replace('run_id=crash-check','run_id=previous-request'),'ProcessExited'),
    (FINALIZER_REUSE_CRASH.replace('stage=wait_combat_end','stage=start_run'),'ProcessExited'),
    (FINALIZER_REUSE_CRASH.replace('at Godot.GodotObject.Finalize()','at OtherFinalizer()'),'ProcessExited'),
])
def test_native_process_exit_requires_wine_crash_signature(tmp_path,message,expected):
    import sys
    from damage_model.worker import GameProcess
    game=GameProcess(tmp_path,tmp_path/'data',
        [sys.executable,'-u','-c','import sys; print(sys.argv[1],flush=True); sys.exit(3)',message],
        log_path=tmp_path/'game.log')
    try:
        result=game.run({'runId':'crash-check','timeoutSeconds':3})
        assert result['status']==expected
        assert message in result['diagnostic'].replace('\r\n', '\n')
        assert game.process is None
    finally: game.stop()


def test_worker_signal_cleans_owned_game(tmp_path,catalog,build):
    import os,subprocess,sys,time,signal
    store=queued(tmp_path,catalog,build)
    config=tmp_path/'runtime.json';log=tmp_path/'fake-game.log'
    config.write_text(json.dumps({'game_dir':str(tmp_path),'data_dir':str(tmp_path/'data'),
        'log_path':str(log),'command':[sys.executable,'-u','-c',
            'import os,time; print(os.getpid(),flush=True); time.sleep(60)']}))
    code="""from damage_model.catalog import Catalog
from damage_model.store import Store
from damage_model.worker import work
import sys
c=Catalog.load('catalogs/game-0.111.0.raw.json','configs/v1.json')
work(Store(sys.argv[1]),c,sys.argv[2],1)
"""
    driver=subprocess.Popen([sys.executable,'-c',code,str(tmp_path/'test.sqlite'),str(config)],
                            cwd=ROOT,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        deadline=time.monotonic()+10
        while (not log.exists() or not log.read_text().strip()) and time.monotonic()<deadline: time.sleep(.05)
        owned_pid=int(log.read_text().strip())
        driver.send_signal(signal.SIGTERM)
        driver.wait(timeout=10)
        assert not Path(f'/proc/{owned_pid}').exists()
        assert store.counts()=={'running':1}  # Lease recovery retries; interruption is never a label.
    finally:
        if driver.poll() is None: driver.kill();driver.wait()
