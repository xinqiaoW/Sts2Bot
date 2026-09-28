"""Synthetic multi-process SQLite/outbox/online-backup probe; no game or real data."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from damage_model.store import Store
from damage_model.schema import Build, Card
from damage_model.result_outbox import record_claim, submit
from tools.rental_backup import snapshot


def worker(directory, index):
    runtime=directory/f'worker-{index:02d}';runtime.mkdir()
    store=Store(directory/'synthetic.sqlite')
    with (runtime/'collector.lock').open('a+') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        while True:
            job=store.claim(330)
            if job is None:break
            record_claim(runtime,job)
            result=dict(status='Passed',combatEnded=True,runId=job['id'],syntheticPayload='x'*8192,
                trainingObservation=dict(complete=True,initialHp=70,initialMaxHp=70,
                finalHp=65,finalMaxHp=70,netHpLoss=5,playerDied=False,
                initialBuild=dict(character='SILENT',ascension=10,actId='OVERGROWTH',
                cards=[dict(id='DEFEND_SILENT',upgradeLevel=1)],relics=[])))
            assert submit(store,runtime,job,result)=='complete'
    store.db.close()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory',type=Path,required=True)
    parser.add_argument('--jobs',type=int,default=4800)
    parser.add_argument('--workers',type=int,default=24)
    parser.add_argument('--timeout',type=int,default=1800)
    parser.add_argument('--child',type=int)
    args=parser.parse_args();directory=args.directory.resolve()
    if args.child is not None:return worker(directory,args.child)
    directory.mkdir()
    store=Store(directory/'synthetic.sqlite')
    build=Build('OVERGROWTH',1,(Card('DEFEND_SILENT',1),),(),(),'synthetic-only')
    store.schedule(build,[{'id':'SYNTHETIC_TARGET'}],map(str,range(args.jobs)),{'synthetic':True})
    store.db.close()
    children=[];logs=[];backups=[];start=time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=1) as executor:
            pending=None;next_backup=start+1
            for index in range(args.workers):
                log=(directory/f'worker-{index:02d}.log').open('x');logs.append(log)
                children.append(subprocess.Popen([sys.executable,__file__,'--directory',str(directory),
                    '--child',str(index)],stdout=log,stderr=subprocess.STDOUT))
            while any(p.poll() is None for p in children):
                if any(p.poll() not in (None,0) for p in children):
                    raise RuntimeError('Synthetic worker failed; see retained worker logs')
                if pending is not None and pending.done():
                    backups.append(pending.result());pending=None
                if pending is None and time.monotonic()>=next_backup:
                    pending=executor.submit(snapshot,directory/'synthetic.sqlite',directory/'backup')
                    next_backup=time.monotonic()+3
                if time.monotonic()-start>args.timeout:raise TimeoutError('Synthetic probe exceeded its elapsed-time budget')
                time.sleep(.1)
            if pending is not None:backups.append(pending.result())
        with sqlite3.connect(directory/'synthetic.sqlite') as db:
            counts=dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
            attempts=db.execute('SELECT count(*),count(DISTINCT job_id),count(DISTINCT lease) FROM attempts').fetchone()
            assert counts=={'complete':args.jobs} and attempts==(args.jobs,)*3
            assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        assert not list(directory.glob('worker-*/pending-submission.json'))
        final=snapshot(directory/'synthetic.sqlite',directory/'final-backup')
        assert final['counts']==counts and backups
        report=dict(passed=True,syntheticOnly=True,workers=args.workers,jobs=args.jobs,
                    wallSeconds=time.monotonic()-start,counts=counts,attempts=attempts,
                    onlineBackups=len(backups),finalBackup=final)
        (directory/'report.json').write_text(json.dumps(report,indent=2)+'\n')
        print(json.dumps(report),flush=True)
    finally:
        for child in children:
            if child.poll() is None:child.terminate()
        for child in children:child.wait(timeout=10)
        for log in logs:log.close()


if __name__=='__main__':main()
