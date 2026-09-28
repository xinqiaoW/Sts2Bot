import importlib.util
import json
from pathlib import Path
import sys
import os
import subprocess
import sqlite3
import time

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
from standalone_rollout_metrics import (cgroup_limits, effective_resources, choose_workers,
                                        combine_batches, search_metrics, soak_gate, sampled_build)


def test_hierarchical_cgroup_memory_and_cpu(tmp_path):
    group = tmp_path / 'user/session'; group.mkdir(parents=True)
    (group.parent/'cpu.max').write_text('3200000 100000')
    (group/'cpu.max').write_text('800000 100000')
    (group.parent/'memory.max').write_text('128000')
    (group.parent/'memory.current').write_text('100000')
    (group/'memory.max').write_text('max')
    limits = cgroup_limits(tmp_path, '0::/user/session\n')
    assert effective_resources(limits, 200000, 256) == {'cpuQuotaCores': 8, 'availableBytes': 28000}


def test_dirty_cache_is_not_counted_as_available_memory():
    limits = [{'memory.max':'1000', 'memory.current':'900',
               'memory.stat':'inactive_file 400\nfile_dirty 100\nfile_writeback 50'}]
    assert effective_resources(limits, 2000, 32)['availableBytes'] == 350
    assert effective_resources(limits, 250, 32)['availableBytes'] == 250


def batch(workers, seconds=100, expanded=100, hp=5, died=False):
    return dict(workers=workers, passed=True, completed=40, wallSeconds=seconds,
                failedAttempts=0, quarantined=0, cases={str(i): dict(complete=True, netHpLoss=hp,
                playerDied=died, firstSearch={'boundary':'TimeLimit', 'expandedNodes':expanded}) for i in range(40)})


def test_faster_pool_rejected_when_search_becomes_shallow():
    result = choose_workers([batch(8), batch(16, 60, 90), batch(32, 40, 50),
                             batch(32, 40, 50), batch(16, 60, 90), batch(8)])
    assert result['selectedWorkers'] == 16
    assert result['candidates'][-1]['eligible'] is False


def test_smaller_pool_preferred_for_negligible_throughput_gain():
    assert choose_workers([batch(8), batch(16, 97), batch(16, 97), batch(8)])['selectedWorkers'] == 8


@pytest.mark.parametrize('change', ['hp', 'death', 'failed'])
def test_labels_and_failures_constrain_concurrency(change):
    fast = batch(16, 50, hp=8 if change == 'hp' else 5, died=change == 'death')
    if change == 'failed': fast['failedAttempts'] = 1
    assert choose_workers([batch(8), fast, fast, batch(8)])['selectedWorkers'] == 8


def test_missing_pairs_do_not_pass():
    with pytest.raises(ValueError): choose_workers([batch(8)])
    altered = batch(16); del altered['cases']['0']
    with pytest.raises(ValueError): choose_workers([batch(8), batch(8), altered, altered])
    assert not choose_workers([batch(8), batch(8)], minimum_pairs=41)['passed']


def test_bad_baseline_cannot_authorize_a_larger_pool():
    bad = batch(8); bad['failedAttempts'] = 1
    assert not choose_workers([bad, batch(16, 50), batch(16, 50), bad])['passed']


def test_supplement_preserves_all_costs_and_does_not_double_count():
    first, second = batch(8), batch(8, 200)
    second['cases'] = {'extra-'+k:v for k,v in second['cases'].items()}
    second['failedAttempts'] = 1
    merged = combine_batches([first], [second])[0]
    assert merged['wallSeconds'] == 300 and merged['completed'] == 80
    assert merged['failedAttempts'] == 1 and len(merged['cases']) == 80
    with pytest.raises(ValueError): combine_batches([first], [first])


def test_diagnostics_ignore_continuations_and_failed_previous_host(tmp_path):
    path = tmp_path/'host.log'
    metric = dict(status='teacher_search_metrics', expandedNodes=100, reused=False, boundary='TimeLimit')
    events = [metric, {'status':'blocked'}, {'status':'native_detour_helper_loaded'},
              {**metric, 'expandedNodes':50}, {**metric, 'reused':True},
              {'status':'StandaloneCompleted', 'runId':'a'}]
    path.write_text('\n'.join(map(json.dumps, events))+'\n')
    result = search_metrics([path])
    assert result['a']['expandedNodes'] == 50 and result['a']['searchCount'] == 1
    with path.open('a') as stream: stream.write(json.dumps(events[-1])+'\n')
    with pytest.raises(ValueError): search_metrics([path])


def test_soak_gate_never_turns_launch_or_short_run_into_acceptance():
    args = dict(duration=86400, completed=10000, failed=0, quarantined=0, running=0,
                audit={'passed':True}, healthy_resources=True, backups_verified=True)
    assert soak_gate(**args)
    for name, value in [('duration', 86399), ('completed',9999), ('failed',1), ('quarantined',102),
                        ('running',1), ('audit', {'passed':False}), ('healthy_resources',False), ('backups_verified',False)]:
        assert not soak_gate(**{**args, name:value}), name


def test_sampling_is_stable_and_independent_of_labels():
    first = [str(i) for i in range(10000) if sampled_build(str(i))]
    assert first == [str(i) for i in range(10000) if sampled_build(str(i))]
    assert 60 < len(first) < 150


def test_audit_pages_completed_attempts_without_duplicate_builds(tmp_path):
    from standalone_rollout_audit import ingest
    index = sqlite3.connect(':memory:')
    index.executescript('''
        CREATE TABLE cursors(name TEXT PRIMARY KEY,value INTEGER);
        CREATE TABLE builds(id TEXT PRIMARY KEY,dataset TEXT,job TEXT,target TEXT,request TEXT);
        CREATE TABLE targets(id TEXT PRIMARY KEY);
        CREATE TABLE cases(id INTEGER PRIMARY KEY,dataset TEXT,job TEXT,build TEXT,target TEXT,
            request TEXT,status TEXT,UNIQUE(dataset,job));
    ''')
    path = tmp_path/'real.sqlite'
    with sqlite3.connect(path) as db:
        db.executescript('''
            CREATE TABLE jobs(id TEXT PRIMARY KEY,build_id TEXT,target TEXT,teacher TEXT);
            CREATE TABLE attempts(id INTEGER PRIMARY KEY,job_id TEXT,status TEXT,result TEXT);
        ''')
        for i in range(260):
            db.execute('INSERT INTO jobs VALUES(?,?,?,?)', (str(i),str(i//2),json.dumps({'id':str(i%80)}),'{}'))
            db.execute('INSERT INTO attempts VALUES(?,?,?,?)', (i+1,str(i),'complete',
                       json.dumps({'collectionRequest':{'runId':str(i)}})))
        # Failed attempts contain no usable request and must never enter the audit.
        db.execute('INSERT INTO attempts VALUES(999,?,?,?)', ('0','failed','{}'))
    for _ in range(4): ingest(index, {'real':path})
    assert index.execute('SELECT count(*) FROM builds').fetchone()[0] == 130
    assert index.execute('SELECT count(*) FROM targets').fetchone()[0] == 80
    assert index.execute('SELECT value FROM cursors').fetchone()[0] == 260
    before = list(index.execute('SELECT * FROM cases ORDER BY id'))
    ingest(index, {'real':path})
    assert before == list(index.execute('SELECT * FROM cases ORDER BY id'))
    # Completion records are appended by Store.finish; a later completion stays visible.
    with sqlite3.connect(path) as db:
        db.execute('INSERT INTO jobs VALUES(?,?,?,?)', ('late','late',json.dumps({'id':'late-target'}),'{}'))
        db.execute('INSERT INTO attempts VALUES(1000,?,?,?)', ('late','complete',
                   json.dumps({'collectionRequest':{'runId':'late'}})))
    ingest(index, {'real':path})
    assert index.execute("SELECT count(*) FROM cases WHERE build='late'").fetchone()[0] == 1


def test_audit_final_topup_counts_distinct_builds_and_retains_failures():
    from standalone_rollout_audit import top_up
    index = sqlite3.connect(':memory:')
    index.executescript('''
        CREATE TABLE builds(id TEXT PRIMARY KEY,dataset TEXT,job TEXT,target TEXT,request TEXT);
        CREATE TABLE cases(id INTEGER PRIMARY KEY,dataset TEXT,job TEXT,build TEXT,target TEXT,
            request TEXT,status TEXT,UNIQUE(dataset,job));
    ''')
    index.executemany('INSERT INTO builds VALUES(?,?,?,?,?)',
                      [(str(i),'real',str(i),'target','{}') for i in range(1001)])
    for i in range(4):
        index.execute('INSERT INTO cases(dataset,job,build,target,request,status) VALUES(?,?,?,?,?,?)',
                      ('real','old-'+str(i),'0','target','{}','native_failed'))
    top_up(index)
    assert index.execute('SELECT count(DISTINCT build) FROM cases').fetchone()[0] == 11
    assert index.execute("SELECT count(*) FROM cases WHERE status='native_failed'").fetchone()[0] == 4
    before = list(index.execute('SELECT * FROM cases ORDER BY id'))
    top_up(index)
    assert before == list(index.execute('SELECT * FROM cases ORDER BY id'))


def test_owned_launcher_rejects_changed_parent():
    result = subprocess.run([sys.executable, str(TOOLS/'run_standalone_rollout.py'),
                             '--owned-exec', '0', '/bin/true'])
    assert result.returncode == 125


def test_owner_death_signals_child_to_drain(tmp_path):
    ready, stopped = tmp_path/'ready', tmp_path/'stopped'
    child_code = ('import signal,time;from pathlib import Path;'
                  f'signal.signal(signal.SIGTERM,lambda *a:(Path({str(stopped)!r}).touch(),exit(0)));'
                  f'Path({str(ready)!r}).touch();time.sleep(30)')
    parent_code = ('import os,subprocess,sys,time;'
                   f'subprocess.Popen([sys.executable,{str(TOOLS/"run_standalone_rollout.py")!r},'
                   f'"--owned-exec",str(os.getpid()),sys.executable,"-c",{child_code!r}]);time.sleep(30)')
    parent = subprocess.Popen([sys.executable, '-c', parent_code])
    try:
        deadline = time.time()+5
        while not ready.exists() and time.time()<deadline: time.sleep(.02)
        assert ready.exists()
        parent.terminate(); parent.wait(timeout=3)
        deadline = time.time()+5
        while not stopped.exists() and time.time()<deadline: time.sleep(.02)
        assert stopped.exists()
    finally:
        if parent.poll() is None: parent.terminate(); parent.wait(timeout=3)
