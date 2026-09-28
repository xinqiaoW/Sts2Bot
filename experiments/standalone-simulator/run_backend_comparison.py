#!/usr/bin/env python3
"""Paired cold-process or native-reuse benchmark in an explicitly isolated Wine experiment directory."""
import argparse
import copy
import datetime
import json
import math
import os
from pathlib import Path
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from damage_model.provenance import sha256, verify_runtime
from damage_model.schema import Build
from damage_model.standalone import StandaloneProcess
from damage_model.store import Store
from damage_model.worker import GameProcess
from replay_evidence import write


class ObservedGameProcess(GameProcess):
    """Keep actual reuse evidence even when failure handling stops the process."""
    def start(self):
        self.started_for_request = True
        super().start()

    def run(self, request):
        had_live_process = self.process is not None and self.process.poll() is None
        self.started_for_request = False
        try:
            return super().run(request)
        finally:
            self.request_process_reused = had_live_process and not self.started_for_request


def summarize(trials, mode="cold"):
    summary = {}
    for backend in ('native-wine', 'standalone-managed-native'):
        selected = [t for t in trials if t['backend'] == backend]
        durations = sorted(t['wallSeconds'] for t in selected)
        if not durations:
            continue
        complete = sum(t['validatedStatus'] == 'complete' for t in selected)
        summary[backend] = dict(attempted=len(selected), complete=complete,
            failed=len(selected)-complete, totalWallSeconds=sum(durations),
            medianWallSeconds=statistics.median(durations),
            p95WallSeconds=durations[math.ceil(len(durations)*0.95)-1],
            validLabelsPerHour=3600*complete/sum(durations))
    if (len(summary) == 2 and len({v['attempted'] for v in summary.values()}) == 1
            and all(t.get('cpuIsolationVerified', True) for t in trials)):
        native, standalone = summary.values()
        summary['totalMeasuredTimeRatio'] = native['totalWallSeconds']/standalone['totalWallSeconds']
        summary['validLabelThroughputRatio'] = (standalone['validLabelsPerHour']/native['validLabelsPerHour']
                                               if native['validLabelsPerHour'] > 0 else None)
        summary[('cold' if mode == 'cold' else 'batch')+'MedianSpeedRatio'] = native['medianWallSeconds']/standalone['medianWallSeconds']
        summary[('cold' if mode == 'cold' else 'batch')+'MedianTimeReductionPercent'] = 100*(1-standalone['medianWallSeconds']/native['medianWallSeconds'])
    return summary


def trial_schedule(cases, repeats, mode):
    for repeat in range(repeats):
        if mode == 'cold':
            for index, case in enumerate(cases):
                order = ['native-wine', 'standalone-managed-native']
                if (repeat+index)%2:
                    order.reverse()
                for backend in order:
                    yield repeat, case, backend, True
        else:
            order = ['native-wine', 'standalone-managed-native']
            if repeat%2:
                order.reverse()
            for backend in order:
                for index, case in enumerate(cases):
                    yield repeat, case, backend, index == len(cases)-1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('experiment-directory', 'native-runtime', 'source-database', 'host-dll', 'progress-snapshot', 'report'):
        parser.add_argument('--'+name, type=Path, required=True)
    parser.add_argument('--dotnet', required=True)
    parser.add_argument('--cpu', type=int, required=True)
    parser.add_argument('--mode', choices=['cold', 'warm-native-batch'], default='cold')
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--teacher-config', type=Path,
                        help='Explicit candidate identity; defaults to the repository teacher')
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Report already exists; preserve prior benchmark evidence')
    if not 1 <= args.repeats <= 20 or args.cpu not in os.sched_getaffinity(0):
        parser.error('Invalid repetition count or unavailable CPU')
    import psutil
    root = Path(__file__).resolve().parents[2]
    isolated = args.experiment_directory.resolve(strict=True)
    runtime = json.loads(args.native_runtime.read_text())
    for path in (runtime['game_dir'], runtime['data_dir'], runtime['env']['WINEPREFIX']):
        if not Path(path).resolve(strict=True).is_relative_to(isolated):
            parser.error('All mutable native runtime paths must be in the isolated experiment directory')
    runtime['env']['DOTNET_PROCESSOR_COUNT'] = '1'
    folder = Path(tempfile.mkdtemp(prefix='paired-cold-', dir=isolated))
    runtime['log_path'] = str(folder/'native.log')
    teacher_config = (args.teacher_config or root/'configs/teacher.json').resolve(strict=True)
    teacher = json.loads(teacher_config.read_text())
    verify_runtime(runtime, teacher)
    standalone_teacher = dict(teacher, execution_backend='standalone-managed-native', validation_scope='isolated-experiment',
        standalone_host_sha256=sha256(args.host_dll), standalone_unlock_state='progress-snapshot', progress_snapshot_sha256=sha256(args.progress_snapshot))
    sruntime = dict(backend='standalone-managed-native', game_dir=runtime['game_dir'], data_dir=str(folder/'standalone'),
        host_dll=str(args.host_dll.resolve()), dotnet=args.dotnet, progress_snapshot=str(args.progress_snapshot.resolve()))
    verify_runtime(sruntime, standalone_teacher)
    progress = Path(runtime['data_dir'])/'default/1/modded/profile1/saves/progress.save'
    if not progress.resolve().is_relative_to(isolated):
        raise ValueError('Progress path escapes isolated directory')
    snapshot = args.progress_snapshot.read_bytes()
    source = sqlite3.connect(args.source_database.resolve().as_uri()+'?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    fixtures = sorted((root/'experiments/standalone-simulator/fixtures').glob('restore-*.json'))
    cases = []
    for path in fixtures:
        fixture = json.loads(path.read_text())
        row = source.execute('SELECT b.body,j.target,j.seed FROM attempts a JOIN jobs j ON j.id=a.job_id JOIN builds b ON b.id=j.build_id WHERE a.id=?', (fixture['attemptId'],)).fetchone()
        if not row:
            raise ValueError('Missing historical source build')
        if json.loads(row['target'])['id'] != fixture['request']['encounterId'] or row['seed'] != fixture['request']['seed']:
            raise ValueError('Fixture/source target or seed mismatch')
        cases.append((path.name, fixture, row))
    source.close()
    previous_affinity = os.sched_getaffinity(0)
    os.sched_setaffinity(0, {args.cpu})
    report = dict(schema='standalone-paired-cold/v1', complete=False, productionReady=False, productionLabels=False,
        mode=args.mode, scope=('Fresh game/host process per trial, alternating pairs.' if args.mode == 'cold' else 'Native process reused within each batch; standalone process per request; alternate whole-batch order. First native startup and final stop included in batch cost.')+' Warmed Wine server; shared pinned CPU; OS cache not controlled.',
        checkedAt=datetime.datetime.now(datetime.timezone.utc).isoformat(), directory=str(folder), cpuAffinity=[args.cpu],
        cpuCount=os.cpu_count(), repeats=args.repeats, nativeTeacher=teacher, standaloneTeacher=standalone_teacher,
        teacherConfig=dict(path=str(teacher_config), sha256=sha256(teacher_config)), progressSnapshotSha256=sha256(args.progress_snapshot),
        hostSha256=sha256(args.host_dll), fixtureHashes={p.name:sha256(p) for p in fixtures},
        sourceHashes={str(p.relative_to(root)):sha256(p) for p in [Path(__file__).resolve(),root/'damage_model/standalone.py',root/'damage_model/worker.py']},
        wallTimeScope='Per-request execution, stop when appropriate, validation and result writing. Fixture preparation and inter-trial report updates excluded; batch first startup/final stop included.',
        resourceCaveat='CPU and RSS sampled every 20ms for the owned process tree; daemonized Wine services excluded, short-lived children may be missed.',
        trials=[], pairs=[])
    args.report.parent.mkdir(parents=True, exist_ok=True)
    native_game = ObservedGameProcess(**runtime)
    paired = {}
    try:
        # Prefix boot is setup, outside cold game startup measurements.
        setup = subprocess.run([runtime['command'][0], 'cmd', '/c', 'exit'], env={**os.environ, **runtime['env']},
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=60)
        if setup.returncode:
            raise RuntimeError('Isolated Wine prefix warmup failed: '+setup.stdout.decode(errors='replace')[-2000:])
        for repeat, (name, fixture, row), backend, close_batch in trial_schedule(cases, args.repeats, args.mode):
            if native_game.process is None:
                progress.write_bytes(snapshot)
            assert sha256(progress) == report['progressSnapshotSha256']
            request = copy.deepcopy(fixture['request']); request['runId'] = uuid.uuid4().hex
            game = native_game if backend == 'native-wine' else StandaloneProcess(**{k:v for k,v in sruntime.items() if k!='backend'})
            starting_pid = game.process.pid if game.process is not None else None
            cpu_base = {}
            if starting_pid is not None:
                try:
                    parent = psutil.Process(starting_pid)
                    for child in [parent]+parent.children(recursive=True):
                        times = child.cpu_times()
                        cpu_base[(child.pid,child.create_time())] = times.user+times.system
                except psutil.Error:
                    pass
            stop = threading.Event(); cpu_times = {}; peak = [0]; affinities = set()
            def sample():
                while not stop.wait(0.02):
                    try:
                        owned = game.process
                        if owned is None:
                            continue
                        parent = psutil.Process(owned.pid)
                        memory = 0
                        for child in [parent]+parent.children(recursive=True):
                            try:
                                affinities.add(tuple(child.cpu_affinity()))
                                times = child.cpu_times(); key = (child.pid,child.create_time())
                                cpu_times[key] = max(cpu_times.get(key,0),max(0,times.user+times.system-cpu_base.get(key,0)))
                                memory += child.memory_info().rss
                            except psutil.Error:
                                pass
                        peak[0] = max(peak[0],memory)
                    except psutil.Error:
                        pass
            sampler=threading.Thread(target=sample,daemon=True);sampler.start()
            load_before=os.getloadavg();started=time.monotonic()
            try:
                result=game.run(request)
                reused = game.request_process_reused if backend == 'native-wine' else False
            finally:
                if args.mode == 'cold' or backend != 'native-wine' or close_batch:
                    game.stop()
                wall=time.monotonic()-started;stop.set();sampler.join()
            result['collectionRequest']=request
            store=Store(folder/(request['runId']+'.sqlite'))
            store.schedule(Build.from_dict(json.loads(row['body'])),[json.loads(row['target'])],[row['seed']],teacher if backend=='native-wine' else standalone_teacher)
            job=store.claim()
            try:
                status=store.finish(job,result)
            except ValueError as error:
                status=store.finish(job,dict(status='InvalidObservation',error=str(error),native_result=result))
            store.db.close()
            result_path=folder/(request['runId']+'.json');write(result_path,result)
            trial=dict(repeat=repeat+1,fixture=name,backend=backend,runId=request['runId'],hostStatus=result['status'],
                validatedStatus=status,nativeProcessReused=reused if backend == 'native-wine' else False,
                nativeReuseEvidence='request_start_observed' if backend == 'native-wine' else None,executionWallSeconds=wall,wallSeconds=time.monotonic()-started,sampledCpuSeconds=sum(cpu_times.values()),sampledPeakRssBytes=peak[0],
                observedCpuAffinities=sorted(affinities),cpuIsolationVerified=affinities=={(args.cpu,)},
                loadAverageBefore=load_before,resultFile=str(result_path),resultSha256=sha256(result_path),
                observation=result.get('trainingObservation'),error=result.get('error'),progressAfterSha256=sha256(progress))
            pair = paired.setdefault((repeat,name), {})
            pair[backend]=trial;report['trials'].append(trial)
            if len(pair) == 2:
                matched=all(t['validatedStatus']=='complete' for t in pair.values()) and pair['native-wine']['observation']==pair['standalone-managed-native']['observation']
                report['pairs'].append(dict(repeat=repeat+1,fixture=name,matched=matched))
            report['summary']=summarize(report['trials'], args.mode);write(args.report,report)
            print(json.dumps({k:trial[k] for k in ('repeat','fixture','backend','validatedStatus','wallSeconds')}),flush=True)
        report['complete']=True;write(args.report,report)
    finally:
        native_game.stop()
        os.sched_setaffinity(0,previous_affinity)


if __name__ == '__main__':
    main()
