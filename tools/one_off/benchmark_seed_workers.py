"""Isolated native throughput experiment. Does not change collection recovery policy."""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import sys
import time

from damage_model.catalog import Catalog
from damage_model.provenance import teacher_for, sha256
from damage_model.schema import Build, canonical, digest
from damage_model.store import Store
from tools.one_off.backfill_targeted_seeds import (
    connect_readonly, copy_build, has_table, manifest_for, prepare_output)


def emit(value):
    print(json.dumps(value, ensure_ascii=False), flush=True)


def prepare(root, per_target=64):
    root = Path(root).resolve()
    cat = Catalog.load('catalogs/game-0.111.0.raw.json', 'configs/real-runs-8s.json')
    teacher = teacher_for(cat, 'configs/teacher.json')
    sources = [Path('data') / ('collection-' + name + '.sqlite') for name in
               ('real-runs-v4', 'mutations-v2', 'targeted-mutations-v1')]
    manifest = manifest_for([p.resolve() for p in sources], cat, teacher)
    ids = {tid for _, tid in cat.encounter_seed_counts}
    reports = []
    for name, path in zip(('real', 'mutation', 'targeted'), sources):
        destination = root / 'template' / (name + '.sqlite')
        destination.parent.mkdir(exist_ok=True)
        emit({'event': 'prepare_source', 'source': str(path)})
        with closing(connect_readonly(path)) as source:
            table = 'mutation_target_origins' if has_table(source, 'mutation_lineage') else 'target_origins'
            candidates = defaultdict(set)
            for bid, tid in source.execute(f'SELECT build_id,target_id FROM {table}'):
                if tid in ids:
                    candidates[tid].add(bid)
            selected = {}
            store = prepare_output(destination, source, manifest, path.resolve())
            try:
                ready = store.db.execute("SELECT value FROM collection_settings WHERE key='benchmark_only'").fetchone()
                if ready:
                    counts = dict(store.db.execute("SELECT json_extract(target,'$.id'),count(DISTINCT build_id) FROM jobs GROUP BY 1"))
                    reports.append({'dataset':name,'jobs':store.db.execute('SELECT count(*) FROM jobs').fetchone()[0],
                                    'builds_per_target':counts})
                    continue
                for tid, bids in sorted(candidates.items()):
                    accepted = []
                    store.db.execute('BEGIN')
                    for bid in sorted(bids, key=lambda value: digest(['seed-benchmark-20260919', tid, value])):
                        completed = source.execute("SELECT 1 FROM jobs WHERE build_id=? AND status='complete' AND json_extract(target,'$.id')=? LIMIT 1", (bid, tid)).fetchone()
                        if not completed:
                            completed = source.execute("SELECT 1 FROM prior_collected_inputs WHERE build_id=? AND target_id=? AND source_status='complete' LIMIT 1", (bid, tid)).fetchone()
                        if not completed:
                            continue
                        row = source.execute('SELECT * FROM builds WHERE id=?', (bid,)).fetchone()
                        build = Build.from_dict(json.loads(row['body']))
                        if (build.act_id, tid) not in cat.encounter_seed_counts:
                            continue
                        cat.validate(build)
                        target = next(t for t in cat.targets(build) if t['id'] == tid)
                        copy_build(store.db, source, row)
                        accepted.append((bid, target, cat.battle_seeds(build.act_id, tid)[4:]))
                        if len(accepted) == per_target:
                            break
                    if accepted:
                        selected[tid] = accepted
                    store.db.commit()
                # Stable encounter round-robin; no queue begins with thousands
                # of seeds belonging to just one monster or one build.
                inserted = 0
                with store.db:
                    for round_index in range(per_target * 20):
                        for tid, builds in sorted(selected.items()):
                            bid, target, seeds = builds[round_index % len(builds)]
                            seed = seeds[round_index // per_target]
                            inserted += store.db.execute('''INSERT OR IGNORE INTO jobs
                                (id,build_id,target,seed,teacher,created) VALUES(?,?,?,?,?,?)''',
                                (digest([bid, tid, seed, teacher]), bid, canonical(target), seed,
                                 canonical(teacher), float(inserted))).rowcount
                    store.db.execute('INSERT OR REPLACE INTO collection_settings VALUES(?,?)',
                                     ('benchmark_only', canonical({'name': 'seed-worker-scaling', 'sources': manifest['sources']})))
                store.db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
                reports.append({'dataset': name, 'jobs': inserted, 'builds_per_target': {k: len(v) for k, v in selected.items()}})
            finally:
                store.db.close()
    (root / 'workload.json').write_text(json.dumps(reports, indent=2))
    emit({'event': 'prepared', 'workload': reports})


def worker(args):
    from damage_model.priority_store import open_allocation
    from damage_model.worker import work
    metrics = Path(args.metrics).open('a', buffering=1)

    def record(event, **fields):
        metrics.write(json.dumps({'time': time.time(), 'event': event, **fields}) + '\n')

    original_begin = Store._begin_write
    original_claim = Store.claim
    original_counts = Store.counts
    original_finish = Store.finish
    original_retry = Store.retry_or_quarantine_native

    def begin(self, operation):
        started = time.perf_counter()
        ok = False
        try:
            value = original_begin(self, operation)
            ok = True
            return value
        finally:
            record('db_begin', operation=operation, seconds=time.perf_counter()-started, success=ok)

    def claim(self, *a, **kw):
        started = time.perf_counter()
        try:
            return original_claim(self, *a, **kw)
        finally:
            record('claim', seconds=time.perf_counter()-started)

    def counts(self):
        started = time.perf_counter()
        try:
            return original_counts(self)
        finally:
            record('counts', seconds=time.perf_counter()-started)

    def finish(self, job, result):
        started = time.perf_counter()
        value = original_finish(self, job, result)
        record('finish', status=value, target=job['target']['id'], dataset=job.get('collection_dataset'),
               job=job['id'], native_ms=result.get('elapsedMilliseconds'), turns=result.get('finishedTurn'),
               loss=(result.get('trainingObservation') or {}).get('netHpLoss'),
               db_finish_seconds=time.perf_counter()-started)
        return value

    def retry(self, job, result, **kw):
        value = original_retry(self, job, result, **kw)
        record('native_failure', status=value, native_status=result.get('status'), target=job['target']['id'])
        return value

    Store._begin_write, Store.claim, Store.counts = begin, claim, counts
    Store.finish, Store.retry_or_quarantine_native = finish, retry
    cat = Catalog.load('catalogs/game-0.111.0.raw.json', 'configs/real-runs-8s.json')
    teacher = teacher_for(cat, 'configs/teacher.json')
    primary = Store(Path(args.stage)/'real.sqlite')
    queue, opened = open_allocation(primary, Path(args.stage)/'mutation.sqlite',
                                    Path(args.stage)/'targeted.sqlite', teacher, offset=args.index % 4)
    record('worker_started', pid=os.getpid())
    try:
        success = work(queue, cat, args.runtime, args.limit, teacher)
        record('worker_stopped', success=success)
        if not success:
            raise SystemExit(2)
    finally:
        for store in [primary, *opened]:
            store.db.close()
        metrics.close()


def read_monitor(backup_pids):
    cpu = [int(n) for n in Path('/proc/stat').read_text().splitlines()[0].split()[1:9]]
    mem = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines()}
    disk = next([int(n) for n in line.split()[3:]] for line in Path('/proc/diskstats').read_text().splitlines() if line.split()[2] == 'sdb')
    io = {}
    for pid in backup_pids:
        try:
            io[str(pid)] = {line.split(':')[0]: int(line.split(':')[1]) for line in Path(f'/proc/{pid}/io').read_text().splitlines()}
        except OSError:
            pass
    cg = Path('/sys/fs/cgroup/user.slice/user-1014.slice')
    return {'time': time.time(), 'cpu': cpu, 'available_gib': mem['MemAvailable']/1024**2,
            'swap_used_gib': (mem['SwapTotal']-mem['SwapFree'])/1024**2,
            'pids': int((cg/'pids.current').read_text()), 'pids_max': int((cg/'pids.max').read_text()),
            'disk': disk, 'backup_io': io, 'load': os.getloadavg()}


def summarize(stage):
    stage = Path(stage)
    meta = json.loads((stage/'stage.json').read_text())
    start, end = meta['measure_start'], meta['measure_end']
    events = []
    for path in (stage/'metrics').glob('*.jsonl'):
        for line in path.read_text().splitlines():
            event = json.loads(line)
            if start <= event['time'] < end:
                events.append(event)
    completed = [e for e in events if e['event'] == 'finish' and e['status'] == 'complete']
    failures = [e for e in events if e['event'] == 'native_failure' or e['event'] == 'finish' and e['status'] != 'complete']
    samples = [json.loads(line) for line in (stage/'monitor.jsonl').read_text().splitlines()]
    samples = [s for s in samples if start <= s['time'] <= end]

    def stats(values):
        values = sorted(values)
        if not values:
            return None
        return {'n': len(values), 'mean': sum(values)/len(values), 'p50': values[len(values)//2],
                'p95': values[min(len(values)-1, int(len(values)*.95))], 'max': values[-1]}

    report = {**meta, 'completed': len(completed), 'failures': len(failures),
              'completed_per_hour': len(completed)*3600/(end-start),
              'failure_fraction': len(failures)/max(1, len(completed)+len(failures)),
              'by_target': dict(Counter(e['target'] for e in completed)),
              'by_dataset': dict(Counter(e['dataset'] for e in completed)),
              'native_seconds': stats(e['native_ms']/1000 for e in completed if isinstance(e.get('native_ms'), (float,int))),
              'db_begin_seconds': stats(e['seconds'] for e in events if e['event'] == 'db_begin'),
              'claim_seconds': stats(e['seconds'] for e in events if e['event'] == 'claim'),
              'counts_seconds': stats(e['seconds'] for e in events if e['event'] == 'counts'),
              'db_finish_seconds': stats(e['db_finish_seconds'] for e in completed if 'db_finish_seconds' in e),
              'db_begins_over_100ms': sum(e['seconds']>.1 for e in events if e['event']=='db_begin'),
              'db_begins_over_1s': sum(e['seconds']>1 for e in events if e['event']=='db_begin'),
              'db_begins_failed': sum(not e['success'] for e in events if e['event']=='db_begin')}
    if len(samples)>1:
        a,b=samples[0],samples[-1]; elapsed=b['time']-a['time']; delta=[y-x for x,y in zip(a['cpu'],b['cpu'])]
        total=sum(delta)
        report['resources']={'cpu_busy_percent':100*(total-delta[3]-delta[4])/total,
            'cpu_iowait_percent':100*delta[4]/total, 'available_gib_min':min(s['available_gib'] for s in samples),
            'pids_max':max(s['pids'] for s in samples), 'swap_growth_gib':b['swap_used_gib']-a['swap_used_gib'],
            'disk_read_mib_s':(b['disk'][2]-a['disk'][2])*512/1024**2/elapsed,
            'disk_write_mib_s':(b['disk'][6]-a['disk'][6])*512/1024**2/elapsed,
            'disk_busy_percent':100*(b['disk'][9]-a['disk'][9])/1000/elapsed,
            'backup_io_deltas':{pid:{k: vals[k]-a['backup_io'][pid][k] for k in ('rchar','wchar','read_bytes','write_bytes')}
                                for pid,vals in b['backup_io'].items() if pid in a['backup_io']}}
    (stage/'report.json').write_text(json.dumps(report, indent=2))
    return report


def run_stage(root, count, seconds=600, warmup=60):
    import fcntl
    config=json.loads(Path('configs/real-runs-8s.json').read_text())
    if config['search_dop']!=1 or config['short_search_budget_ms']!=8000:
        raise ValueError('The scaling experiment requires DOP 1 and the unchanged 8-second search budget')
    root=Path(root).resolve(); stage=root/f'workers-{count:03d}'
    stage.mkdir(exist_ok=False); (stage/'metrics').mkdir(); (stage/'logs').mkdir()
    runtimes=json.loads((root/'runtimes.json').read_text())[:count]
    for name in ('real','mutation','targeted'):
        with closing(connect_readonly(root/'template'/f'{name}.sqlite')) as source:
            with closing(sqlite3.connect(stage/f'{name}.sqlite')) as dest:
                source.backup(dest)
    backup_pids=[]
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit(): continue
        try: command=(proc/'cmdline').read_bytes()
        except OSError: continue
        if b'tools.local_backup' in command and b'--db' in command:
            backup_pids.append(int(proc.name))
    configs=[json.loads(Path(r).read_text()) for r in runtimes]
    # Verify all runtimes are idle before touching markers or starting children.
    for config in configs:
        with (Path(config['data_dir'])/'collector.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    children=[]; logs=[]; meta={'workers':count,'warmup_seconds':warmup,'requested_seconds':seconds,'started':time.time(),
                               'before_start':read_monitor(backup_pids), 'benchmark_sha256':sha256(__file__),
                               'config_sha256':sha256('configs/real-runs-8s.json')}
    monitor=(stage/'monitor.jsonl').open('a',buffering=1)
    error=None
    def interrupted(signum, frame):
        raise KeyboardInterrupt(f'Benchmark interrupted by signal {signum}')
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,interrupted)
    try:
        for i,path in enumerate(runtimes):
            sample=read_monitor(backup_pids)
            if sample['available_gib']<4 or sample['pids']>sample['pids_max']-160:
                raise RuntimeError('Insufficient memory or remaining thread slots to start another runtime')
            (Path(configs[i]['data_dir'])/'collector.stop').unlink(missing_ok=True)
            log=(stage/'logs'/f'worker-{i:03d}.log').open('ab'); logs.append(log)
            child=subprocess.Popen([sys.executable,'-u','-m','tools.one_off.benchmark_seed_workers','worker',
                '--stage',str(stage),'--index',str(i),'--runtime',path,'--metrics',str(stage/'metrics'/f'{i:03d}.jsonl')],
                stdout=log,stderr=subprocess.STDOUT)
            children.append(child)
            time.sleep(2)
        meta['measure_start']=time.time()+warmup; meta['measure_end']=meta['measure_start']+seconds
        (stage/'stage.json').write_text(json.dumps(meta,indent=2))
        emit({'event':'stage_started',**meta,'pids':[c.pid for c in children]})
        while time.time()<meta['measure_end']:
            sample=read_monitor(backup_pids);monitor.write(json.dumps(sample)+'\n')
            bad=[(i,c.poll()) for i,c in enumerate(children) if c.poll() is not None]
            if bad: raise RuntimeError(f'Worker exited before the measurement deadline: {bad}')
            if sample['available_gib']<4: raise RuntimeError('Host memory exhausted during benchmark')
            time.sleep(5)
    except BaseException as exc:
        error=str(exc);meta['error']=error
        if 'measure_start' not in meta: meta['measure_start']=meta['started']
        meta['measure_end']=max(meta['measure_start']+.001,time.time())
        emit({'event':'stage_error','workers':count,'error':error})
    finally:
        for config in configs:
            (Path(config['data_dir'])/'collector.stop').touch()
        deadline=time.monotonic()+160
        while any(c.poll() is None for c in children) and time.monotonic()<deadline: time.sleep(1)
        for c in children:
            if c.poll() is None: c.send_signal(signal.SIGINT)
        for c in children:
            try: c.wait(timeout=15)
            except subprocess.TimeoutExpired: c.kill();c.wait()
        meta['exit_codes']=[c.returncode for c in children]; meta['drained_at']=time.time()
        (stage/'stage.json').write_text(json.dumps(meta,indent=2));monitor.close()
        for stream in logs: stream.close()
    report=summarize(stage);emit({'event':'stage_complete','report':report})
    if error: raise RuntimeError(error)


def main():
    parser=argparse.ArgumentParser();sub=parser.add_subparsers(dest='command',required=True)
    p=sub.add_parser('prepare');p.add_argument('--root',required=True);p.add_argument('--per-target',type=int,default=64)
    p=sub.add_parser('worker');p.add_argument('--stage',required=True);p.add_argument('--runtime',required=True)
    p.add_argument('--index',type=int,required=True);p.add_argument('--metrics',required=True)
    p.add_argument('--limit',type=int,default=10000)
    p=sub.add_parser('run');p.add_argument('--root',required=True);p.add_argument('--workers',nargs='+',type=int,default=[25,40,60,80])
    p.add_argument('--seconds',type=int,default=600);p.add_argument('--warmup',type=int,default=60)
    p=sub.add_parser('summarize');p.add_argument('--stage',required=True)
    args=parser.parse_args()
    if args.command=='prepare': prepare(args.root,args.per_target)
    elif args.command=='worker': worker(args)
    elif args.command=='summarize': emit(summarize(args.stage))
    else:
        for count in args.workers: run_stage(args.root,count,args.seconds,args.warmup)


if __name__=='__main__': main()
