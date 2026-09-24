#!/usr/bin/env python3
"""Freeze distinct real deck/relic states before native differential execution."""
import argparse,collections,hashlib,json,sqlite3,sys
from pathlib import Path
sys.dont_write_bytecode=True
p=argparse.ArgumentParser(description=__doc__)
for n in ('source-root','source-database','directory'):p.add_argument('--'+n,type=Path,required=True)
p.add_argument('--required-builds',type=int,default=10000)
p.add_argument('--reserve-builds',type=int,default=500)
a=p.parse_args();sys.path.insert(0,str(a.source_root))
from damage_model.catalog import Catalog
from damage_model.schema import Build,digest
from damage_model.worker import request_for
from damage_model.provenance import teacher_for
from build_panel_contract import composition_key as composition
catalog=Catalog.load(a.source_root/'catalogs/game-0.111.0.raw.json',a.source_root/'configs/real-runs-8s.json');teacher=teacher_for(catalog,a.source_root/'configs/teacher.json')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
assert a.required_builds>0 and a.reserve_builds>=0
out=a.directory;out.mkdir(exist_ok=True);assert not (out/'plan.json').exists() and not (out/'cases.sqlite').exists()
c=sqlite3.connect(a.source_database.resolve().as_uri()+'?mode=ro',uri=True);c.execute('BEGIN')
candidates={};rejected=collections.Counter();examined=0
for bid,body in c.execute('SELECT id,body FROM builds ORDER BY id'):
 examined+=1;build=Build.from_dict(json.loads(body))
 try:catalog.validate(build)
 except ValueError as e:rejected[str(e)]+=1;continue
 assert build.id==bid
 targets=sorted(catalog.targets(build),key=lambda t:t['id']);seed=catalog.battle_seeds(build.act_id,targets[0]['id'])[0]
 request=request_for(dict(id=bid,build=build.to_dict(),target=targets[0],seed=seed,teacher=teacher),catalog.config)
 key=composition(request)
 if key in candidates:rejected['duplicate_deck_and_relic_state']+=1;continue
 candidates[key]=dict(build=build.to_dict(),sourceBuildId=bid,sourceJobId='source-build:'+bid,sourceBodySha256=hashlib.sha256(body.encode()).hexdigest(),compositionKey=key)
 if examined%5000==0:print(json.dumps(dict(examined=examined,distinct=len(candidates))),flush=True)
c.rollback();c.close()
by_act=collections.defaultdict(list)
for key,record in sorted(candidates.items(),key=lambda kv:digest(['10000-build-panel-v1',kv[0]])):
 by_act[record['build']['act_id']].append(record)
chosen=[];acts=sorted(by_act);needed=a.required_builds+a.reserve_builds
assert len(candidates)>=needed,(len(candidates),needed)
for index in range(max(map(len,by_act.values()))):
 for act in acts:
  if index<len(by_act[act]):chosen.append(by_act[act][index])
  if len(chosen)==needed:break
 if len(chosen)==needed:break
counts=collections.Counter();act_counts=collections.Counter();builds={};request_keys=set()
db=sqlite3.connect(out/'cases.sqlite');db.execute('CREATE TABLE cases(case_index INTEGER PRIMARY KEY, case_id TEXT NOT NULL UNIQUE, body TEXT NOT NULL)')
with db:
 for i,record in enumerate(chosen):
  build=Build.from_dict(record['build']);targets=sorted(catalog.targets(build),key=lambda t:t['id']);j=act_counts[build.act_id];target=targets[j%len(targets)];seeds=catalog.battle_seeds(build.act_id,target['id']);seed_index=(j//len(targets))%len(seeds);seed=seeds[seed_index]
  cid=digest([build.id,target['id'],seed]);req=request_for(dict(id=cid,build=build.to_dict(),target=target,seed=seed,teacher=teacher),catalog.config);req['runId']=digest(['frozen-request',cid])[:32]
  assert composition(req)==record['compositionKey'];k=digest({n:v for n,v in req.items() if n not in ('runId','scenarioId')});assert k not in request_keys;request_keys.add(k)
  case=dict(caseId=cid,sourceJobId=record['sourceJobId'],sourceBuildId=build.id,request=req,target=target['id'],seed=seed,act=build.act_id,seedIndex=seed_index,compositionKey=record['compositionKey'])
  db.execute('INSERT INTO cases VALUES(?,?,?)',(i,cid,json.dumps(case,sort_keys=True)));builds[build.id]=record;counts[target['id']]+=1;act_counts[build.act_id]+=1
assert db.execute('PRAGMA integrity_check').fetchone()[0]=='ok';db.close();assert len(counts)==80 and len(builds)==needed
plan=dict(schema='distinct-build-panel/v1',productionReady=False,productionLabels=False,buildCount=needed,requiredValidatedBuilds=a.required_builds,targetCount=80,caseCount=needed,checkpointTarget=0,caseDatabase=str((out/'cases.sqlite').resolve()),caseDatabaseSha256=sha(out/'cases.sqlite'),builds=builds,teacher=teacher,priorActuallyPlayedCards=[],catalogSha256=sha(a.source_root/'catalogs/game-0.111.0.raw.json'),sourceDatabase=str(a.source_database.resolve()),sourceBuildsExamined=examined,eligibleByAct={act:len(v) for act,v in by_act.items()},rejections=dict(rejected),casesByTarget=dict(counts),casesByAct=dict(act_counts),selection='Deterministic hash-ranked real builds, interleaved across acts; one formal target and fixed formal seed per unique deck/relic state; target and seed rotation fixed before execution. No combat outcomes used for selection. Extra 500 inputs are preselected reserves for native capture failures, never replacements for replay mismatches.',uniqueness='Sorted actual request card multiset (including upgrades, enchantments and saved state) plus ordered relic request states. Ignores source IDs, act/history, encounter and seed; one battle per composition.',stopPolicy='At least 10000 distinct successfully replayed builds, all 80 formal targets, and zero unresolved replay differences. Drain in-flight work and independently audit all captures; failures and unfinished inputs count zero. Successful native recordings may never be replaced to hide replay failures.',scriptSha256=sha(Path(__file__)))
(out/'plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({k:v for k,v in plan.items() if k not in ['builds','teacher','casesByTarget']},ensure_ascii=False),flush=True)
