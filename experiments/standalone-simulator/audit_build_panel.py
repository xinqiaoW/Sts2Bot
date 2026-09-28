#!/usr/bin/env python3
"""Independently audit full states for at least 10000 distinct frozen builds."""
import argparse,fcntl,json,sqlite3,sys
from contextlib import ExitStack
from pathlib import Path
sys.dont_write_bytecode=True
from replay_evidence import validate_replay,terminal,identity,normalized,require,write
from build_panel_contract import validate_build_panel, build_acceptance_passed


def audit(source_root,directory,plan_path,host_dll,checkpoint_target):
 plan=json.loads(plan_path.read_text())
 validation=validate_build_panel(plan,source_root)
 host=identity(host_dll);require(identity(plan['caseDatabase'])['sha256']==plan['caseDatabaseSha256'],'Panel database changed')
 progress=identity(source_root/'experiments/standalone-simulator/fixtures/pilot-progress-v24.json')
 base_teacher=json.loads((source_root/'configs/teacher.json').read_text())
 require(all(plan['teacher'].get(k)==v for k,v in base_teacher.items()),'Panel runtime teacher changed')
 def relocated(path):
  original=Path(path)
  for old,new in plan.get('nativeEvidencePathAliases',{}).items():
   if original.is_relative_to(old):return Path(new)/original.relative_to(old)
  return original
 database=sqlite3.connect(Path(plan['caseDatabase']).as_uri()+'?mode=ro',uri=True)
 seen=set();builds=set();targets=set();checked=[];unresolved=[];native_failures=[];stale=[];played=set();choices=0
 for result_path in sorted((directory/'cases').glob('*/result.json')):
  entry=json.loads(result_path.read_text());case_id=entry['caseId'];require(case_id not in seen,'Duplicate case result');seen.add(case_id)
  row=database.execute('SELECT case_index,body FROM cases WHERE case_id=?',(case_id,)).fetchone();require(row is not None,'Result outside frozen panel');case=json.loads(row[1]);require(entry['caseIndex']==row[0],'Case index changed')
  if entry.get('hostSha256')!=host['sha256']:
   stale.append(dict(caseId=case_id,result=identity(result_path)));continue
  capture_count=len(entry['captureAttempts']);require(1<=capture_count<=3,'Capture attempt limit exceeded')
  native=None
  for index,attempt in enumerate(entry['captureAttempts'],1):
   require(attempt['attempt']==index,'Capture attempt gap')
   require(native is None,'Successful capture was retried')
   if attempt.get('recording'):
    record=Path(attempt['recording']['path']);require(identity(record)==attempt['recording'],'Recording changed')
    candidate=json.loads(record.read_text());require(normalized(candidate['request'])==normalized(case['request']),'Native request differs from panel')
    if candidate.get('complete'):
     # Captures store the runtime teacher; the panel also includes policy fields.
     # The complete policy request is compared with its frozen case above.
     require(candidate['teacher']==base_teacher,'Native teacher differs from frozen panel')
     require(candidate['progressSnapshotSha256']==progress['sha256'],'Native progress snapshot changed')
     first=candidate['events'][0];require(first['kind']=='initialized','Native initialization missing')
     require(first['value']['assemblySha256']==candidate['traceModSha256'],'Native trace module identity differs')
     require(first['value']['collectorSha256']==plan['teacher']['collector_sha256'],'Native solver identity differs')
     trace_file=relocated(candidate['directory'])/(candidate['request']['runId']+'.jsonl' if first['value'].get('reusableProcess') else 'trace.jsonl')
     emitted=[json.loads(line) for line in trace_file.read_text().splitlines()]
     require(emitted==candidate['events'],'Capture differs from original emitted native trace')
     if first['value'].get('reusableProcess'):
      require(first['value']['runId']==candidate['request']['runId'],'Reusable trace belongs to a different request')
      require(first['value']['progressSnapshotSha256']==progress['sha256'],'Reusable process did not restore frozen progress')
     native=candidate
  if native is None:
   require(entry['passed'] is False,'No successful native capture');native_failures.append(dict(caseId=case_id,result=identity(result_path)));continue
  if not entry['passed']:
   unresolved.append(dict(caseId=case_id,stage=entry.get('failureStage'),result=identity(result_path)));continue
  require(entry['replayExecution']['exitCode']==0 and not entry['replayExecution']['timedOut'],'Replay did not complete normally')
  require(identity(relocated(entry['replayCommand'][1]))['sha256']==host['sha256'],'Replay command used a different host')
  fixture=Path(entry['fixture']['path']);log=Path(entry['replayLog']['path']);require(identity(fixture)==entry['fixture'] and identity(log)==entry['replayLog'],'Replay evidence changed')
  source=json.loads(fixture.read_text());require(source['nativeTrace']==native and source['request']==native['request'],'Replay used a different recording')
  stats=validate_replay(native,terminal(log));require(stats['checkpoints']==entry['checkpoints'] and stats['plays']==entry['plays'],'Summary counts differ from actual points')
  played.update(e['value']['action']['CardId'] for e in native['events'] if e['kind']=='play')
  choices+=sum(e['kind']=='choice_plan' and bool(e['value']['choices']) for e in native['events'])
  builds.add(case['sourceBuildId']);targets.add(case['target']);checked.append(dict(caseId=case_id,result=identity(result_path),**stats))
 database.close();points=sum(x['checkpoints'] for x in checked)
 passed=build_acceptance_passed(plan,matched_builds=len(builds),matched_targets=len(targets),unresolved=len(unresolved),stale=len(stale),checkpoint_count=points,checkpoint_target=checkpoint_target)
 return dict(schema='distinct-build-panel-audit/v1',requiredValidatedBuilds=plan['requiredValidatedBuilds'],panelValidation=validation,productionReady=False,productionLabels=False,passed=passed,checkpointTarget=checkpoint_target,matchedCheckpoints=points,
  matchedBattles=len(checked),matchedPlays=sum(x['plays'] for x in checked),uniqueBuilds=len(builds),uniqueTargets=len(targets),plannedCases=plan['caseCount'],unexecutedCases=plan['caseCount']-len(seen),campaignDrained=False,
  actualPlayedCards=sorted(played),newActuallyPlayedCards=sorted(played-set(plan['priorActuallyPlayedCards'])),nonemptyChoicePlans=choices,
  unresolvedReplayDifferences=unresolved,nativeCaptureFailures=native_failures,staleHostResults=stale,host=host,teacher=base_teacher,progressSnapshot=progress,plan=identity(plan_path),auditor=identity(__file__),
  counting='One count per individually verified named state checkpoint in each unique completed (build,target,seed) case. Duplicate runs/fields/attempts do not add counts. Every native state text and replay state text is checked independently against the recorded event.',runs=checked)


def lock_drained_campaign(directory,locks):
 """Hold controller and every native worker lock throughout a final audit."""
 setup=json.loads((directory/'setup.json').read_text())
 paths=[directory/'batch.lock']
 for runtime in setup['runtimes']:
  data=Path(json.loads(Path(runtime).read_text())['data_dir'])
  paths.append(data/'collector.lock')
 for path in paths:
  # Missing ownership evidence is not proof of drain. Do not create new locks.
  lock=locks.enter_context(path.open('r'))
  try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
  except BlockingIOError as error:raise ValueError('Campaign still active: '+str(path)) from error


def main():
 p=argparse.ArgumentParser(description=__doc__)
 for n in ('source-root','directory','plan','host-dll','output'):p.add_argument('--'+n,type=Path,required=True)
 p.add_argument('--checkpoint-target',type=int,default=500000);p.add_argument('--allow-partial',action='store_true')
 a=p.parse_args()
 require(not a.output.exists(),'Refusing to overwrite audit')
 with ExitStack() as locks:
  if not a.allow_partial:lock_drained_campaign(a.directory,locks)
  report=audit(a.source_root,a.directory,a.plan,a.host_dll,a.checkpoint_target)
  report['campaignDrained']=not a.allow_partial
  write(a.output,report)
 print(json.dumps({k:v for k,v in report.items() if k not in ['runs','unresolvedReplayDifferences','nativeCaptureFailures','staleHostResults','actualPlayedCards','newActuallyPlayedCards']}))
 if not report['passed'] and not a.allow_partial:raise SystemExit(1)


if __name__=='__main__':main()
