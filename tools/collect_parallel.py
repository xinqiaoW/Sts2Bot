"""Supervise a bounded set of independent collectors and train only after all finish."""
import argparse
import fcntl
import json
import math
from pathlib import Path
import signal
import subprocess
import sys
import time

from damage_model.store import Store
from damage_model.worker import interrupt_collector


def available_gib():
    values=dict(line.split(':',1) for line in Path('/proc/meminfo').read_text().splitlines())
    return int(values['MemAvailable'].split()[0])/1024**2


def validate_memory_bounds(reserve_gib, worker_start_gib):
    if (not math.isfinite(reserve_gib) or (reserve_gib != 0 and reserve_gib < 4)
            or not math.isfinite(worker_start_gib) or worker_start_gib < 2):
        raise ValueError('Reserve must be 0 (disabled) or at least 4 GiB; budget at least 2 GiB per new worker')


def deadline_reached(stop_at):
    return stop_at is not None and time.time() >= stop_at


def validate_runtimes(paths):
    runtimes=[json.loads(Path(p).read_text()) for p in paths]
    for key in ('data_dir','prefix'):
        values=[str(Path(r['data_dir'] if key=='data_dir' else r['env']['WINEPREFIX']).resolve()) for r in runtimes]
        if len(set(values))!=len(values): raise ValueError(f'Workers share {key}')
    return runtimes


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--db',default='data/collection-real-runs-v2.sqlite')
    p.add_argument('--config',default='configs/real-runs.json')
    p.add_argument('--fallback-db', help='Optional mutation queue sharing these workers')
    p.add_argument('--runtimes',nargs='+',required=True)
    p.add_argument('--reserve-gib',type=float,default=32,help='Available memory reserve; 0 disables reserve-based draining')
    p.add_argument('--worker-start-gib',type=float,default=3)
    p.add_argument('--limit-per-worker',type=int,default=6080)
    p.add_argument('--train-after',action='store_true')
    p.add_argument('--stop-at',type=float,help='UTC Unix deadline; drain current battles and stop')
    args=p.parse_args()
    for sig in (signal.SIGINT,signal.SIGTERM): signal.signal(sig,interrupt_collector)
    if args.limit_per_worker<1: raise ValueError('Invalid resource bounds')
    validate_memory_bounds(args.reserve_gib, args.worker_start_gib)
    if args.stop_at is not None and (not math.isfinite(args.stop_at) or args.stop_at <= 0):
        raise ValueError('Invalid collection deadline')
    configs=validate_runtimes(args.runtimes)
    primary=Store(args.db)
    from damage_model.priority_store import open_priority
    store,fallback=open_priority(primary,args.fallback_db)
    status_path=Path(args.db).with_suffix('.parallel.json')
    lock=Path(args.db).with_suffix('.pool.lock').open('a+')
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    fallback_lock = None
    if fallback is not None:
        fallback_lock = Path(args.fallback_db).with_suffix('.pool.lock').open('a+')
        fcntl.flock(fallback_lock, fcntl.LOCK_EX|fcntl.LOCK_NB)
    children=[]
    log_files=[]
    markers=[Path(r['data_dir'])/'collector.stop' for r in configs]
    def status(state,**extra):
        value={'state':state,'updated':time.time(),'pid':__import__('os').getpid(),
               'counts':primary.counts(),'combined_counts':store.counts(),
               'mutation_counts':fallback.counts() if fallback is not None else {},
               'workers':len(children),'available_gib':available_gib(),
               'reserve_gib':args.reserve_gib,'worker_start_gib':args.worker_start_gib,**extra}
        temporary=status_path.with_suffix('.tmp');temporary.write_text(json.dumps(value,indent=2));temporary.replace(status_path)
    def drain():
        for marker in markers: marker.touch()
        deadline=time.monotonic()+160
        while any(child.poll() is None for child in children) and time.monotonic()<deadline: time.sleep(.5)
        for child in children:
            if child.poll() is None: child.send_signal(signal.SIGINT)
        for child in children:
            try: child.wait(timeout=10)
            except subprocess.TimeoutExpired: child.kill();child.wait(timeout=5)
    def stop_at_deadline():
        if not deadline_reached(args.stop_at): return False
        status('draining',reason='Requested collection deadline')
        drain()
        status('paused',reason='Requested collection deadline')
        return True
    try:
        if store.counts().get('failed',0): raise ValueError('Diagnose failed jobs before starting pool')
        for path,marker in zip(args.runtimes,markers):
            if stop_at_deadline(): return
            if available_gib()<args.reserve_gib+args.worker_start_gib: raise RuntimeError('Insufficient available memory to add a worker')
            marker.unlink(missing_ok=True)
            log=Path('logs')/(Path(path).stem+'-worker.log');log.parent.mkdir(exist_ok=True)
            stream=log.open('ab');log_files.append(stream)
            child=subprocess.Popen([sys.executable,'-u','-m','damage_model.cli','--db',args.db,
                '--config',args.config,
                'work','--runtime',path,'--limit',str(args.limit_per_worker),
                *(['--fallback-db',args.fallback_db] if args.fallback_db else [])],stdout=stream,stderr=subprocess.STDOUT)
            children.append(child)
            status('starting',child_pids=[c.pid for c in children])
            time.sleep(2)
        while any(child.poll() is None for child in children):
            if stop_at_deadline(): return
            if store.counts().get('failed',0) or any(c.poll() not in (None,0) for c in children):
                raise RuntimeError('A collector failed; draining the other workers')
            if args.reserve_gib > 0 and available_gib()<args.reserve_gib:
                raise RuntimeError('Available memory fell below reserve; draining workers')
            status('collecting',child_pids=[c.pid for c in children])
            time.sleep(3)
        if any(c.returncode!=0 for c in children): raise RuntimeError('A collector exited unsuccessfully')
        counts=store.counts()
        if counts.get('failed',0): raise RuntimeError('Failed samples require diagnosis')
        if counts.get('running',0) or counts.get('pending',0):
            status('batch_complete');return
        if args.train_after:
            status('training')
            subprocess.run([sys.executable,'-u','-m','damage_model.cli','--db',args.db,'--config',args.config,'train','--device','cpu'],check=True)
        status('complete')
    except BaseException as error:
        status('draining',error=str(error));drain();status('failed',error=str(error))
        raise
    finally:
        for stream in log_files: stream.close()
        lock.close()
        if fallback_lock is not None: fallback_lock.close()
        if fallback is not None: fallback.db.close()
        primary.db.close()


if __name__=='__main__': main()
