#!/usr/bin/env python3
"""Run the frozen 10000-distinct-build panel with retained native evidence."""
import argparse,fcntl,json,os,sqlite3,subprocess,sys,time,traceback
from pathlib import Path
from contextlib import ExitStack
import psutil
sys.dont_write_bytecode=True
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--source-root',type=Path,required=True);parser.add_argument('--directory',type=Path,required=True)
parser.add_argument('--plan',type=Path);parser.add_argument('--setup',type=Path);parser.add_argument('--host-dll',type=Path,required=True);parser.add_argument('--checkpoint-target',type=int);parser.add_argument('--report-name',default='report.json');parser.add_argument('--worker-index',type=int);parser.add_argument('--only-first',action='store_true');args=parser.parse_args()
root=args.source_root;folder=args.directory
sys.path.insert(0,str(root));sys.path.insert(0,str(root/'experiments/standalone-simulator'));sys.path.insert(0,str(root/'experiments/native-trace-probe'))
from persistent_capture import PersistentCapture
from replay_evidence import validate_replay,terminal,identity,normalized,write
from build_panel_contract import validate_build_panel, build_acceptance_passed
from damage_model.provenance import verify_runtime
from resource_limits import available_memory_bytes
plan_path=args.plan or folder/'plan.json';setup_path=args.setup or folder/'setup.json'
plan=json.loads(plan_path.read_text())
if args.worker_index is None:validate_build_panel(plan, root)
setup=json.loads(setup_path.read_text());checkpoint_target=args.checkpoint_target or plan.get('checkpointTarget',0)
host=args.host_dll;host_sha=identity(host)['sha256']
progress=root/'experiments/standalone-simulator/fixtures/pilot-progress-v24.json'
dotnet=os.environ.get('STS2_CHECKPOINT_DOTNET','/data2/pl/ImageTask/wxq/Projects/dotnet/dotnet')
stop=folder/(args.report_name+'.stop');case_root=folder/'cases';case_root.mkdir(exist_ok=True)
env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1','DOTNET_PROCESSOR_COUNT':'1','TMPDIR':str(folder)};env.pop('COMPlus_TieredCompilation',None);env.pop('DOTNET_TieredCompilation',None)
env['STS2_NATIVE_STARTUP_LOCK_DIR']=str(folder/'native-startup-slots')
env['STS2_NATIVE_STARTUP_SLOTS']=os.environ.get('STS2_NATIVE_STARTUP_SLOTS','8')

def wait_for_memory():
    while available_memory_bytes() < 24 * 2**30:
        time.sleep(5)


def invoke(command,log,timeout):
    # Capture owns its game process group. On wrapper timeout retain the entire
    # process tree before terminating, including descendants with separate groups.
    wait_for_memory()
    with log.open('w') as stream:
        process=subprocess.Popen(command,cwd=folder,env=env,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
        try:return dict(exitCode=process.wait(timeout=timeout),timedOut=False)
        except subprocess.TimeoutExpired:
            try:children=psutil.Process(process.pid).children(recursive=True)
            except psutil.NoSuchProcess:children=[]
            for child in reversed(children):
                try:child.terminate()
                except psutil.NoSuchProcess:pass
            process.terminate()
            _,alive=psutil.wait_procs(children,timeout=5)
            for child in alive:
                try:child.kill()
                except psutil.NoSuchProcess:pass
            try:process.wait(timeout=5)
            except subprocess.TimeoutExpired:process.kill();process.wait()
            return dict(exitCode=process.returncode,timedOut=True)


def worker(index):
    runtime_path=Path(setup['runtimes'][index]);runtime=json.loads(runtime_path.read_text());isolated=runtime_path.parent
    for path in [runtime['game_dir'],runtime['data_dir'],runtime['env']['WINEPREFIX']]:assert Path(path).resolve().is_relative_to(isolated.resolve())
    verify_runtime(runtime,plan['teacher'])
    with (Path(runtime['data_dir'])/'collector.lock').open('a+') as lock, ExitStack() as resources:
        persistent=None
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        if 'caseDatabase' in plan:
            with sqlite3.connect(Path(plan['caseDatabase']).as_uri()+'?mode=ro',uri=True) as database:
                assigned=[(i,json.loads(body)) for i,body in database.execute('SELECT case_index,body FROM cases WHERE case_index % ? = ? ORDER BY case_index',(len(setup['runtimes']),index))]
        else:
            assigned=[(i,c) for i,c in enumerate(plan['cases']) if i%len(setup['runtimes'])==index]
        if args.only_first:assigned=assigned[:1]
        failures=0
        for case_index,case in assigned:
            if stop.exists():break
            case_dir=case_root/f'{case_index:03d}-{case["caseId"][:12]}';case_dir.mkdir(exist_ok=True)
            result_path=case_dir/'result.json'
            if result_path.exists():
                previous=json.loads(result_path.read_text())
                if previous.get('hostSha256')==host_sha:continue
                archived=result_path.with_name('result.before-'+previous.get('hostSha256','legacy')[:12]+'.json')
                if not archived.exists():write(archived,previous)
            source=case_dir/'request.json'
            if not source.exists():write(source,dict(attemptId=0,request=case['request'],sourceJobId=case['sourceJobId'],sourceBuildId=case['sourceBuildId']))
            assert json.loads(source.read_text())['request']==case['request']
            entry=dict(hostSha256=host_sha,caseIndex=case_index,caseId=case['caseId'],target=case['target'],act=case['act'],seed=case['seed'],sourceBuildId=case['sourceBuildId'],worker=index,passed=False,captureAttempts=[])
            write(case_dir/'started.json',dict(caseId=case['caseId'],pid=os.getpid(),startedAt=time.time()))
            native=None
            try:
                for attempt in range(1,4):
                    raw=case_dir/f'native-attempt-{attempt}.json';receipt=case_dir/f'capture-attempt-{attempt}.json';log=case_dir/f'capture-attempt-{attempt}.log'
                    if not raw.exists():
                        if persistent is None:
                            wait_for_memory()
                            persistent=PersistentCapture(isolated,runtime_path,progress,setup['traceDll'])
                            resources.callback(persistent.close)
                        wait_for_memory()
                        execution=persistent.capture(source,raw,log)
                        write(receipt,dict(runtime=identity(runtime_path),fixture=identity(source),**execution))
                    else:execution=json.loads(receipt.read_text()) if receipt.exists() else dict(exitCode=None,recoveredWithoutExitCode=True)
                    capture=json.loads(raw.read_text()) if raw.exists() else None
                    detail=dict(attempt=attempt,**execution,recording=identity(raw) if raw.exists() else None,log=identity(log) if log.exists() else None,nativeStatus=capture['result'].get('status') if capture else None,complete=bool(capture and capture.get('complete')))
                    entry['captureAttempts'].append(detail)
                    if capture and capture.get('complete'):
                        assert normalized(capture['request'])==normalized(case['request'])
                        assert capture['progressSnapshotSha256']==identity(progress)['sha256']
                        native=capture;break  # Never retry a successful recording after a replay mismatch.
                if native is None:
                    entry['failureStage']='native_capture';failures+=1
                else:
                    failures=0
                    fixture=case_dir/'native-replay.json';write(fixture,dict(attemptId=0,request=native['request'],nativeTrace=native,expected=native['result']['trainingObservation'],sourceJobId=case['sourceJobId'],sourceBuildId=case['sourceBuildId']))
                    command=[dotnet,str(host),runtime['game_dir'],'--replay-native-request',str(fixture),str(progress)]
                    log=case_dir/('replay.'+host_sha[:12]+'.log');replayed=invoke(command,log,120)
                    entry.update(replayCommand=command,replayExecution=replayed,fixture=identity(fixture),replayLog=identity(log))
                    if replayed['exitCode']!=0:entry['failureStage']='standalone_replay'
                    else:
                        try:
                            entry.update(validate_replay(native,terminal(log)));entry['passed']=True
                        except (ValueError,KeyError,TypeError) as error:entry.update(failureStage='independent_audit',error=str(error))
                    entry['traceModSha256']=native['traceModSha256']
                    entry['nativeCaptureScriptSha256']=native['captureScriptSha256']
                    entry['actualPlayedCards']=sorted({e['value']['action']['CardId'] for e in native['events'] if e['kind']=='play'})
                    entry['nonemptyChoicePlans']=sum(e['kind']=='choice_plan' and bool(e['value']['choices']) for e in native['events'])
            except Exception:
                entry.update(failureStage='harness',error=traceback.format_exc());failures+=1
            write(result_path,entry)
            print(json.dumps({k:entry.get(k) for k in ['caseIndex','target','passed','failureStage','error']}),flush=True)
            if failures>=3:
                write(folder/f'worker-{index}-halt.json',dict(reason='Three consecutive native/harness failures; inspect before resuming',caseIndex=case_index));break
    return 0


def summarize(exit_codes=None):
    entries=[json.loads(p.read_text()) for p in sorted(case_root.glob('*/result.json'))]
    assert len({x['caseId'] for x in entries})==len(entries)
    by_stage={};actual=set()
    for entry in entries:
        if not entry['passed']:by_stage[entry.get('failureStage','unknown')]=by_stage.get(entry.get('failureStage','unknown'),0)+1
        actual.update(entry.get('actualPlayedCards',[]))
    report=dict(schema='broad-native-parity/v1',productionReady=False,productionLabels=False,complete=len(entries)==plan['caseCount'],passed=len(entries)==plan['caseCount'] and all(x['passed'] for x in entries),
                expectedCases=plan['caseCount'],finishedCases=len(entries),matchedCases=sum(x['passed'] for x in entries),failuresByStage=by_stage,
                plan=identity(plan_path),host=identity(host),progressSnapshot=identity(progress),traceDll=identity(setup['traceDll']),
                traceModulesUsed=sorted({e['traceModSha256'] for e in entries if e.get('traceModSha256')}),runner=identity(__file__),nativeCaptureScript=identity(root/'experiments/native-trace-probe/persistent_capture.py'),startupSlots=env['STS2_NATIVE_STARTUP_SLOTS'],startupLimiter=identity(root/'experiments/native-trace-probe/startup_slots.py'),
                totalPlays=sum(e.get('plays',0) for e in entries if e.get('hostSha256')==host_sha),totalCheckpoints=sum(e.get('checkpoints',0) for e in entries if e.get('hostSha256')==host_sha),
                actualPlayedCards=sorted(actual),newActuallyPlayedCards=sorted(actual-set(plan['priorActuallyPlayedCards'])),
                captureAttempts=sum(len(e['captureAttempts']) for e in entries),failedCaptures=sum(not a['complete'] for e in entries for a in e['captureAttempts']),
                runs=entries,workerExitCodes=exit_codes,scope='Instrumented fixed-action semantics, not a speed benchmark. Native process reuse waits on original readiness and restores pinned progress before every request. All cases preselected; capture failures retained with at most three attempts; successful recordings never replaced to hide mismatches.')
    report.update(checkpointTarget=checkpoint_target,checkpointTargetReached=checkpoint_target>0 and report['totalCheckpoints']>=checkpoint_target,validatedBuildCount=len({e['sourceBuildId'] for e in entries if e['passed']}),validatedTargetCount=len({e['target'] for e in entries if e['passed']}),unresolvedReplayDifferences=sum(e.get('failureStage') in ('standalone_replay','independent_audit') for e in entries),currentHostOnly=all(e.get('hostSha256')==host_sha for e in entries))
    report['requiredValidatedBuilds']=plan['requiredValidatedBuilds']
    report['requestedComparisonPassed']=build_acceptance_passed(plan,matched_builds=report['validatedBuildCount'],matched_targets=report['validatedTargetCount'],unresolved=report['unresolvedReplayDifferences'],stale=sum(e.get('hostSha256')!=host_sha for e in entries),checkpoint_count=report['totalCheckpoints'],checkpoint_target=checkpoint_target)
    write(folder/args.report_name,report)
    return report


def main():
    if args.worker_index is not None:return worker(args.worker_index)
    lockfile=(folder/'batch.lock').open('a+');fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
    assert setup['complete']
    if 'caseDatabase' in plan:assert identity(plan['caseDatabase'])['sha256']==plan['caseDatabaseSha256']
    # Existing completed cases are immutable, allowing continuation after a stopped run.
    cpus=sorted(os.sched_getaffinity(0));chosen=cpus[64:64+len(setup['runtimes'])] if len(cpus)>=64+len(setup['runtimes']) else cpus[:len(setup['runtimes'])]
    children=[];streams=[]
    for index,_ in enumerate(setup['runtimes']):
        log=(folder/f'worker-{index}-driver.log').open('a');streams.append(log)
        command=['taskset','-c',str(chosen[index%len(chosen)]),sys.executable,str(Path(__file__).resolve()),'--source-root',str(root),'--directory',str(folder),'--worker-index',str(index),'--plan',str(plan_path),'--setup',str(setup_path),'--host-dll',str(host),'--report-name',args.report_name,'--checkpoint-target',str(checkpoint_target)]
        if args.only_first:command.append('--only-first')
        children.append(subprocess.Popen(command,cwd=folder,env=env,stdout=log,stderr=subprocess.STDOUT))
    try:
        previous=-1
        while True:
            codes=[p.poll() for p in children];report=summarize(codes)
            if report['finishedCases']!=previous:print(json.dumps({k:report[k] for k in ['finishedCases','matchedCases','failuresByStage','totalCheckpoints']}),flush=True);previous=report['finishedCases']
            if report['requestedComparisonPassed'] and not stop.exists():
                write(stop,dict(reason='10000 distinct matched builds and all targets reached; draining in-flight battles',builds=report['validatedBuildCount'],checkpoints=report['totalCheckpoints']))
            if all(c is not None for c in codes):break
            time.sleep(15)
    finally:
        for stream in streams:stream.close()
        lockfile.close()
    return 0 if (args.only_first and report['matchedCases']==len(setup['runtimes'])) or report['passed'] or report['requestedComparisonPassed'] else 1

if __name__=='__main__':raise SystemExit(main())
