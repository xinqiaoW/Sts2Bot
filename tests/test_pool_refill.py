"""Exercise the real pool loop with isolated locks and deterministic fake workers."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

pytest.importorskip('fcntl')
from tools import collect_parallel as pool
import damage_model.priority_store as priority


def exercise(tmp_path, monkeypatch, *, continuous=True, scenario='normal', targeted=False):
    monkeypatch.chdir(tmp_path)
    runtimes=[]
    for i in range(3):
        data=tmp_path/f'worker-{i}';data.mkdir()
        p=tmp_path/f'runtime-{i}.json'
        p.write_text(json.dumps({'data_dir':str(data),'env':{'WINEPREFIX':str(tmp_path/f'prefix-{i}')}}))
        runtimes.append(str(p))
    state={'pending':0 if scenario=='empty' else 10,'stopped':False}
    class Store:
        def __init__(self,*a): self.db=SimpleNamespace(close=lambda:None)
        def counts(self): return {'pending':state['pending'],'complete':0,'running':0}
    monkeypatch.setattr(pool,'Store',Store)
    monkeypatch.setattr(priority,'open_priority',lambda primary,fallback:(primary,Store()))
    monkeypatch.setattr(priority,'open_allocation',lambda primary,fallback,targeted:(primary,[Store(),Store()]))
    commands=[];children=[];statuses=[]
    class Child:
        def __init__(self,number):
            self.pid=500+number
            self.returncode=0 if number in (0,2) else None
            if scenario=='failure' and number==1:self.returncode=1
        def poll(self):return self.returncode
        def send_signal(self,sig):self.returncode=1
        def wait(self,timeout=None):return self.returncode
        def kill(self):self.returncode=1
    def launch(cmd,**kwargs):
        assert len(commands)<6, 'Unexpected respawn loop'
        commands.append(cmd);child=Child(len(children));children.append(child)
        if len(children)==3 and scenario=='stop':
            (tmp_path/'worker-0/collector.stop').touch()
        return child
    def sleep(seconds):
        p=tmp_path/'real.parallel.json'
        if p.exists():statuses.append(json.loads(p.read_text()))
        if seconds in (.5,3):
            state['pending']=0
            for c in children:
                if c.returncode is None:c.returncode=0
    monkeypatch.setattr(pool.subprocess,'Popen',launch)
    monkeypatch.setattr(pool.time,'sleep',sleep)
    monkeypatch.setattr(pool.signal,'signal',lambda *a:None)
    monkeypatch.setattr(pool,'available_gib',lambda:1 if scenario=='memory' and len(commands)>=3 else 64)
    monkeypatch.setattr(pool,'deadline_reached',lambda deadline:scenario=='deadline' and len(commands)>=3)
    args=['pool','--db','real.sqlite','--fallback-db','mutation.sqlite','--mutation-workers','1',
          '--runtimes',*runtimes,'--reserve-gib','0','--worker-start-gib','2','--limit-per-worker','2']
    if continuous:args.append('--continuous-workers')
    if targeted:
        args[args.index('--mutation-workers')+1]='0'
        args+=['--targeted-db','targeted.sqlite']
    if scenario=='deadline':args+=['--stop-at','100']
    monkeypatch.setattr(pool.sys,'argv',args)
    if scenario=='failure':
        with pytest.raises(RuntimeError,match='collector failed'):pool.main()
    else:pool.main()
    return commands,children,statuses,json.loads((tmp_path/'real.parallel.json').read_text()),runtimes


def test_three_queue_refill_preserves_slot_phase_and_database(tmp_path,monkeypatch):
    commands,_,_,final,paths=exercise(tmp_path,monkeypatch,targeted=True)
    assert [cmd[cmd.index('--schedule-offset')+1] for cmd in commands]==['0','1','2','0','2']
    assert all('--prefer-dataset' not in cmd for cmd in commands)
    assert all(cmd[cmd.index('--targeted-db')+1]=='targeted.sqlite' for cmd in commands)
    assert final['dataset_cycle']==['real','real','mutation','targeted']
    assert final['schedule_offsets']==dict(zip(paths,[0,1,2]))
    assert final['preferred_workers']=={}


def test_refills_fast_real_and_mutation_slots_without_waiting_for_slow_worker(tmp_path,monkeypatch):
    commands,children,statuses,final,paths=exercise(tmp_path,monkeypatch)
    assert len(commands)==5
    assert [cmd[cmd.index('--runtime')+1] for cmd in commands]==[paths[0],paths[1],paths[2],paths[0],paths[2]]
    assert [cmd[cmd.index('--prefer-dataset')+1] for cmd in commands]==['real','real','mutation','real','mutation']
    assert all(cmd[cmd.index('--fallback-db')+1]=='mutation.sqlite' for cmd in commands)
    assert any(s.get('child_pids')==[503,501,504] for s in statuses)
    assert final['worker_restarts']==[1,0,1] and final['state']=='complete'


def test_bounded_pool_still_finishes_without_refilling(tmp_path,monkeypatch):
    commands,_,_,final,_=exercise(tmp_path,monkeypatch,continuous=False)
    assert len(commands)==3 and final['worker_restarts']==[0,0,0]


@pytest.mark.parametrize('scenario',['empty','stop','memory','deadline','failure'])
def test_no_refill_after_empty_queue_stop_low_start_memory_deadline_or_failure(tmp_path,monkeypatch,scenario):
    commands,_,_,final,_=exercise(tmp_path,monkeypatch,scenario=scenario)
    assert len(commands)==3 and final['worker_restarts']==[0,0,0]
    if scenario=='failure':assert final['state']=='failed'
    if scenario=='deadline':assert final['state']=='paused'


def test_continuous_workers_cannot_trigger_training(monkeypatch):
    monkeypatch.setattr(pool.sys,'argv',['pool','--runtimes','unused.json','--continuous-workers','--train-after'])
    monkeypatch.setattr(pool.signal,'signal',lambda *a:None)
    with pytest.raises(ValueError,match='--train-after'):pool.main()
