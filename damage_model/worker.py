from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid
from .schema import Build


def startup_cache_failure(text):
    return ('MaxEnumValueCache.Get[' in text
            and 'A concurrent update was performed on this collection and corrupted its state' in text)


def wine_page_fault(text):
    return 'wine: Unhandled page fault on ' in text and 'starting debugger...' in text


def menu_cleanup_failure(text, run_id):
    # Godot can abort rebuilding input settings after combat. Require this
    # request's cleanup stage and the exact native assertion/stack, not SIGILL alone.
    marker=f'[CombatSolver/Unattended] STAGE run_id={run_id} stage=cleanup '
    position=text.rfind(marker)
    if position<0: return False
    tail=text[position:]
    return all(fragment in tail for fragment in (
        'ERROR: FATAL: Index p_index = ', 'is out of bounds (size() = 0).',
        'at: get (./core/templates/cowdata.h:187)', 'NInputSettingsEntry.Create',
        'NGame+<LoadMainMenu>', 'Fatal error. 0xC000001D'))


def finalizer_cleanup_failure(text, run_id):
    marker=f'[CombatSolver/Unattended] STAGE run_id={run_id} stage=cleanup '
    position=text.rfind(marker)
    if position<0: return False
    tail=text[position:]
    return all(fragment in tail for fragment in (
        'Fatal error. 0xC0000005', 'at Godot.GodotObject.Dispose(Boolean)',
        'at Godot.GodotObject.Finalize()', 'at System.GC.RunFinalizers()'))


def finalizer_reuse_failure(text, run_id):
    accepted = text.rfind(f'[CombatSolver/Unattended] REQUEST_ACCEPTED run_id={run_id} ')
    if accepted < 0 or 'reused_process=True' not in text[accepted:].splitlines()[0]:
        return False
    stage = text.rfind(f'[CombatSolver/Unattended] STAGE run_id={run_id} stage=wait_combat_end ')
    if stage < accepted:
        return False
    tail = text[stage:]
    return all(fragment in tail for fragment in (
        'Fatal error. 0xC0000005', 'at Godot.GodotObject.Dispose(Boolean)',
        'at Godot.GodotObject.Finalize()', 'at System.GC.RunFinalizers()'))


def interrupt_collector(signum, frame):
    raise KeyboardInterrupt(f'Collector received signal {signum}')


def asset_loading_failure(text, run_id):
    marker = f'[CombatSolver/Unattended] STAGE run_id={run_id} stage=start_run '
    position = text.rfind(marker)
    if position < 0: return False
    tail = text[position:]
    if f'STAGE run_id={run_id} stage=' in tail[len(marker):]: return False
    return all(part in tail for part in (
        'Fatal error. 0xC0000005', 'AssetLoadingSession.CheckLoadingStatus()',
        'AssetLoadingSession.Process()', 'NAssetLoader._Process',
        'at: _ref (core/variant/array.cpp:63)'))


def request_for(job, config):
    build=Build.from_dict(job['build'])
    run_id=uuid.uuid4().hex
    return {
        'schemaVersion':1,'runId':run_id,'scenarioId':'HP-'+job['id'][:16],
        'characterId':'SILENT','ascension':10,'seed':job['seed'],
        'encounterId':job['target']['id'],'actIndexForTest':build.act-1,
        'trainingCollection':True,'trainingActId':build.act_id,
        'clearRunDeck':True,'runCards':[{'cardId':c.id,'count':1,'upgradeLevels':c.upgrade,
            **({'enchantmentId': c.enchantment_id, 'enchantmentAmount': c.enchantment_amount} if c.enchantment_id else {})}
            for c in build.cards],
        'cards':[], 'potions':[],
        'relics':[{'relicId':r.id,
                   'addWithoutObtainedEffects': build.mutation in ('spire_codex_run_v1', 'real_run_mutation_v1'),
                   'integerMembers':{k:v for k,v in r.state if type(v) is int},
                   'booleanMembers':{k:v for k,v in r.state if type(v) is bool}}
                  for r in build.relics if r.id!='RING_OF_THE_SNAKE'],
        'potionPolicyForTest':'Disabled','forceShortSearchOnly':True,
        'shortSearchBudgetOverrideMilliseconds':config['short_search_budget_ms'],
        'searchMaxDegreeOfParallelismForTest':config['search_dop'],
        'enableNoGcRegionForTest':False,'performancePresetForTest':'Medium',
        'headlessFastModeForTest':'Instant','deploymentFastModeForTest':'Instant',
        'deploymentInterActionDelaySecondsForTest':0,
        'enableDetailedDiagnosticLogsForTest':False,
        'timeoutSeconds':config['battle_timeout_seconds'],'exitOnComplete':False,
    }


class GameProcess:
    """One owned process and user-data directory per worker; no shared live saves."""
    def __init__(self, game_dir, data_dir, command, env=None, log_path=None):
        self.game_dir=Path(game_dir).resolve(); self.data_dir=Path(data_dir).resolve()
        self.command=command; self.env={**os.environ,**(env or {})}
        self.log_path=Path(log_path or self.data_dir/'worker.log')
        self.process=None; self.log=None
        self.last_run_id=None
        self.data_dir.mkdir(parents=True,exist_ok=True)

    def start(self):
        self.log_path.parent.mkdir(parents=True,exist_ok=True)
        self.log=self.log_path.open('ab')
        self.diagnostic_offset=self.log.tell()
        self.diagnostic_tail=''
        self.process=subprocess.Popen(self.command,cwd=self.game_dir,env=self.env,
            stdout=self.log,stderr=subprocess.STDOUT,start_new_session=os.name!='nt')

    def stop(self):
        if self.process:
            if os.name=='nt':
                if self.process.poll() is None: self.process.terminate()
            else:
                # A crashed parent may leave its Wine debugger in our process group.
                try: os.killpg(self.process.pid,signal.SIGTERM)
                except ProcessLookupError: pass
            try: self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                if os.name=='nt': self.process.kill()
                else: os.killpg(self.process.pid,signal.SIGKILL)
                self.process.wait(timeout=5)
        if self.log: self.log.close()
        self.process=None; self.log=None

    def run(self, request):
        request_path=self.data_dir/'combat_solver_test_request.json'
        ready_path=self.data_dir/'combat_solver_test_ready.json'
        result_path=self.data_dir/'combat_solver_test_result.json'
        if self.process and self.process.poll() is not None: self.stop()
        if self.process and self.process.poll() is None:
            deadline=time.monotonic()+15
            while True:
                if ready_path.exists():
                    ready=json.loads(ready_path.read_text(encoding='utf-8-sig'))
                    if ready.get('schemaVersion')==1 and ready.get('runId')==self.last_run_id and ready.get('held') is False:
                        break
                if self.process.poll() is not None or time.monotonic()>deadline:
                    self.stop(); break
                time.sleep(0.1)
        # These protocol markers belong exclusively to this worker's data directory.
        # A previously unused enum can race on a later battle in a reused process.
        # Restrict detection to new bytes for this request, not the whole log.
        self.diagnostic_offset=self.log_path.stat().st_size if self.log_path.exists() else 0
        self.diagnostic_tail=''
        ready_path.unlink(missing_ok=True)
        temporary=request_path.with_suffix('.tmp')
        temporary.write_text(json.dumps(request),encoding='utf-8')
        temporary.replace(request_path)
        if not self.process or self.process.poll() is not None: self.start()
        deadline=time.monotonic()+request['timeoutSeconds']+30
        while time.monotonic()<deadline:
            with self.log_path.open('rb') as log:
                log.seek(self.diagnostic_offset)
                chunk=log.read(128*1024);self.diagnostic_offset=log.tell()
            self.diagnostic_tail=(self.diagnostic_tail+chunk.decode('utf-8',errors='replace'))[-256*1024:]
            if startup_cache_failure(self.diagnostic_tail):
                error=self.diagnostic_tail[-8000:]
                self.stop()
                return {'runId':request['runId'],'status':'NativeEnumCacheFailure',
                        'error':'Native MaxEnumValueCache concurrent mutation',
                        'diagnostic':error}
            if result_path.exists():
                result=json.loads(result_path.read_text(encoding='utf-8-sig'))
                if result.get('runId')==request['runId'] and result.get('status') in ('Passed','Failed'):
                    self.last_run_id=request['runId']
                    if result['status']=='Failed': self.stop()
                    return result
            if self.process.poll() is not None:
                # Drain the end of this request's log after a process exits; the
                # crash message can be written between the preceding read and poll.
                with self.log_path.open('rb') as log:
                    log.seek(max(self.diagnostic_offset,self.log_path.stat().st_size-256*1024))
                    tail=log.read().decode('utf-8',errors='replace')
                diagnostic=(self.diagnostic_tail+tail)[-256*1024:]
                if wine_page_fault(diagnostic):
                    status,error='NativeWinePageFault','Wine native page fault'
                elif menu_cleanup_failure(diagnostic,request['runId']):
                    status,error='NativeMenuCleanupFailure','Godot input settings assertion during this request cleanup'
                elif finalizer_cleanup_failure(diagnostic,request['runId']):
                    status,error='NativeFinalizerCleanupFailure','Godot object finalizer access violation during this request cleanup'
                elif finalizer_reuse_failure(diagnostic,request['runId']):
                    status,error='NativeFinalizerReuseFailure','Godot object finalizer access violation in a reused native game during this request combat'
                elif asset_loading_failure(diagnostic,request['runId']):
                    status,error='NativeAssetLoadingFailure','Godot array access violation while loading assets before combat'
                else:
                    status,error='ProcessExited','Game exited before producing result'
                self.stop()
                return {'runId':request['runId'],
                        'status':status,'error':error,
                        'diagnostic':diagnostic[-16000:] if status in ('NativeMenuCleanupFailure','NativeFinalizerCleanupFailure','NativeFinalizerReuseFailure') else diagnostic[-8000:]}
            time.sleep(0.1)
        self.stop()
        return {'runId':request['runId'],'status':'Timeout','error':'No terminal game result before worker deadline'}


def work(store,catalog,runtime_config,limit,teacher=None):
    from .resilience import NATIVE_FAILURES, native_failure_policy, preserve_failure
    failure_policy = native_failure_policy(catalog.config)
    consecutive_isolations = 0
    runtime=json.loads(Path(runtime_config).read_text(encoding='utf-8'))
    if teacher is not None:
        from .provenance import verify_runtime
        verify_runtime(runtime,teacher)
        existing=store.db.execute('SELECT DISTINCT teacher FROM jobs').fetchall()
        from .schema import canonical
        if any(row[0]!=canonical(teacher) for row in existing):
            raise ValueError('Worker settings do not match queued teacher')
    game=GameProcess(**runtime)
    if os.name!='posix': raise ValueError('This collector runtime requires Linux process isolation')
    import fcntl
    lease_file=(game.data_dir/'collector.lock').open('a+')
    try:
        fcntl.flock(lease_file,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lease_file.close()
        raise RuntimeError('Another collector owns this game data directory') from None
    handlers={sig:signal.signal(sig,interrupt_collector) for sig in (signal.SIGINT,signal.SIGTERM)}
    try:
        for _ in range(limit):
            if (game.data_dir/'collector.stop').exists(): break
            if store.counts().get('failed',0): return False
            job=store.claim(catalog.config['battle_timeout_seconds']+90)
            if job is None: break
            build=Build.from_dict(job['build']); catalog.validate(build)
            if build.mutation == 'real_run_mutation_v1':
                from .mutations import validate_lineage
                owner = store.owner(job) if hasattr(store, 'owner') else store
                validate_lineage(owner.db, build.id, catalog)
            if job['target']['id'] not in {t['id'] for t in catalog.targets(build)}: raise ValueError('Target/act mismatch')
            request=request_for(job,catalog.config)
            log_offset = game.log_path.stat().st_size if game.log_path.exists() else 0
            result=game.run(request)
            result['collectionRequest']=request
            result['collector']={'worker':Path(runtime_config).stem,'pid':os.getpid(),
                                 'host':os.uname().nodename}
            if failure_policy and result.get('status') in NATIVE_FAILURES:
                # Every retry starts a fresh owned game process. Preserve evidence before
                # making the job eligible again, so another worker cannot race the copy.
                game.stop()
                evidence_dir = failure_policy['evidence_directory']
                if build.mutation == 'real_run_mutation_v1':
                    mutation_policy = json.loads(owner.db.execute("SELECT value FROM collection_settings WHERE key='mutation_policy'").fetchone()[0])
                    evidence_dir = mutation_policy['evidence_directory']
                evidence, reason = preserve_failure(game, job, result, log_offset, evidence_dir)
                status = store.retry_or_quarantine_native(job, result,
                    max_attempts=failure_policy['max_attempts'], reason=reason, evidence=evidence)
                print(json.dumps({'job':job['id'],'target':job['target']['id'],'status':status,
                                  'native_status':result['status'],'evidence':evidence}),flush=True)
                if status == 'quarantined':
                    consecutive_isolations += 1
                    if consecutive_isolations >= 3:
                        raise RuntimeError('Three consecutive native job isolations; diagnose systemic runtime failure')
                continue
            if result.get('status') in ('NativeStartupCacheFailure','NativeEnumCacheFailure','NativeWinePageFault','NativeMenuCleanupFailure','NativeFinalizerCleanupFailure','NativeFinalizerReuseFailure','NativeAssetLoadingFailure'):
                status=store.retry_startup(job,result)
                print(json.dumps({'job':job['id'],'status':status,'reason':result['error']}),flush=True)
                if status=='failed': return False
                continue
            try:
                status=store.finish(job,result)
            except ValueError as error:
                status=store.finish(job,{'status':'InvalidObservation','error':str(error),'native_result':result})
            print(json.dumps({'job':job['id'],'target':job['target']['id'],'status':status,
                             'observation':result.get('trainingObservation')},ensure_ascii=False),flush=True)
            # A failed native scenario is a diagnostic boundary, not a reason to create
            # thousands of identical bad jobs. Leave the rest pending for diagnosis.
            if status!='complete': return False
            consecutive_isolations = 0
        return True
    finally:
        game.stop()
        lease_file.close()
        for sig,handler in handlers.items(): signal.signal(sig,handler)
