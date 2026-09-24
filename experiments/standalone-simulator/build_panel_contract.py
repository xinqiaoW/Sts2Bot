"""Validate actual build diversity and case bindings, not caller-supplied IDs."""
import collections,hashlib,json,sqlite3,sys
from pathlib import Path

def composition_key(request):
 # Ignore provenance, IDs, act/history and encounter/seed. Identical card multisets
 # plus ordered relics/counters count once even if obtained in different runs/acts.
 from damage_model.schema import digest,canonical
 return digest(dict(runCards=sorted(request['runCards'],key=canonical),relics=request['relics']))

def validate_build_panel(plan,root):
 sys.path.insert(0,str(root))
 from damage_model.catalog import Catalog
 from damage_model.schema import Build,digest
 from damage_model.worker import request_for
 from damage_model.provenance import teacher_for
 def need(ok,message):
  if not ok:raise ValueError(message)
 need(plan['schema']=='distinct-build-panel/v1','Wrong build panel schema')
 need(plan['requiredValidatedBuilds']>=10000,'Build target below 10000')
 need(plan['buildCount']>=plan['requiredValidatedBuilds'],'Too few planned builds')
 need(plan['targetCount']==80,'Formal target count changed')
 dbpath=Path(plan['caseDatabase']);need(hashlib.sha256(dbpath.read_bytes()).hexdigest()==plan['caseDatabaseSha256'],'Frozen database changed')
 catalog=Catalog.load(root/'catalogs/game-0.111.0.raw.json',root/'configs/real-runs-8s.json')
 need(hashlib.sha256((root/'catalogs/game-0.111.0.raw.json').read_bytes()).hexdigest()==plan['catalogSha256'],'Catalog changed')
 need(teacher_for(catalog,root/'configs/teacher.json')==plan['teacher'],'Frozen teacher changed')
 seen=set();build_ids=set();targets=set();requests=set();indices=[];by_act=collections.Counter()
 with sqlite3.connect(dbpath.resolve().as_uri()+'?mode=ro',uri=True) as db:
  for index,cid,body in db.execute('SELECT case_index,case_id,body FROM cases ORDER BY case_index'):
   case=json.loads(body);bid=case['sourceBuildId'];need(bid not in build_ids,'Repeated source build')
   record=plan['builds'][bid];build=Build.from_dict(record['build']);catalog.validate(build);need(build.id==bid,'Forged build ID')
   key=composition_key(case['request']);need(key not in seen,'Duplicate actual deck and relic state')
   need(key==record['compositionKey']==case['compositionKey'],'Composition key differs')
   target=next((t for t in catalog.targets(build) if t['id']==case['target']),None);need(target is not None,'Invalid formal target')
   need(case['act']==build.act_id,'Case act differs');need(case['seed'] in catalog.battle_seeds(build.act_id,target['id']),'Nonformal seed')
   need(cid==case['caseId']==digest([bid,target['id'],case['seed']]),'Case identity differs')
   expected=request_for(dict(id=cid,build=build.to_dict(),target=target,seed=case['seed'],teacher=plan['teacher']),catalog.config)
   normalize=lambda q:{k:v for k,v in q.items() if k not in ('runId','scenarioId')}
   need(normalize(expected)==normalize(case['request']),'Request does not implement frozen build')
   request_key=digest(normalize(case['request']));need(request_key not in requests,'Duplicate gameplay input')
   seen.add(key);requests.add(request_key);build_ids.add(bid);targets.add(target['id']);indices.append(index);by_act[build.act_id]+=1
 need(indices==list(range(plan['caseCount'])),'Case indices/count differ')
 need(len(seen)==len(build_ids)==plan['buildCount']==len(plan['builds']),'Build count differs')
 need(len(targets)==80,'Formal targets missing')
 return dict(passed=True,uniqueActualBuilds=len(seen),uniqueRequests=len(requests),targets=len(targets),buildsByAct=dict(by_act))

def build_acceptance_passed(plan, *, matched_builds, matched_targets, unresolved, stale,
                            checkpoint_count=0, checkpoint_target=0):
 return (plan['requiredValidatedBuilds']>=10000
         and matched_builds>=plan['requiredValidatedBuilds']
         and matched_targets==plan['targetCount']==80
         and unresolved==0 and stale==0
         and checkpoint_count>=checkpoint_target>=0)
