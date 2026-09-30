#!/usr/bin/env python3
"""Revalidate all existing build-panel recordings with one new immutable host.

The source campaign is read-only. Failed and successful native captures are
preserved; there is no capture retry or selection of convenient recordings.
"""
import argparse
import concurrent.futures
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

from replay_evidence import identity, terminal, validate_replay, require, write


def replay_case(source_result, destination, host, runtime, progress):
    previous = json.loads(source_result.read_text())
    # Keep only capture/input evidence. Never inherit a previous host's counts.
    entry = {k: previous[k] for k in ('caseIndex', 'caseId', 'target', 'act', 'seed',
             'sourceBuildId', 'captureAttempts')}
    entry.update(hostSha256=identity(host)['sha256'], passed=False,
                 previousResult=identity(source_result))
    case = destination / 'cases' / source_result.parent.name
    case.mkdir(parents=True)
    try:
        native = None
        for attempt in entry['captureAttempts']:
            require(native is None, 'Successful native capture was retried')
            if not attempt.get('recording'):
                continue
            path = Path(attempt['recording']['path'])
            require(identity(path) == attempt['recording'], 'Original recording changed')
            captured = json.loads(path.read_text())
            if captured.get('complete'):
                native = captured
        if native is None:
            entry['failureStage'] = 'native_capture'
        else:
            fixture = Path(previous['fixture']['path'])
            require(identity(fixture) == previous['fixture'], 'Original fixture changed')
            original = json.loads(fixture.read_text())
            require(original['nativeTrace'] == native and original['request'] == native['request'],
                    'Fixture uses a different successful native recording')
            log = case / 'replay.log'
            command = [runtime['dotnet'], str(host), runtime['game_dir'], '--replay-native-request',
                       str(fixture), str(progress)]
            execution = dict(timedOut=False)
            start = time.monotonic()
            with log.open('x') as stream:
                try:
                    execution['exitCode'] = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                        env=dict(os.environ, DOTNET_PROCESSOR_COUNT='1', DOTNET_TieredCompilation='0'),
                        timeout=120).returncode
                except subprocess.TimeoutExpired:
                    execution.update(timedOut=True, exitCode=None)
            execution['wallSeconds'] = time.monotonic() - start
            entry.update(fixture=identity(fixture), replayCommand=command,
                         replayExecution=execution, replayLog=identity(log))
            if execution['exitCode'] != 0:
                entry['failureStage'] = 'standalone_replay'
            else:
                entry['failureStage'] = 'independent_audit'
                entry.update(validate_replay(native, terminal(log)), passed=True)
                del entry['failureStage']
    except Exception as error:
        entry.update(passed=False, failureStage=entry.get('failureStage', 'evidence'),
                     error=repr(error))
    write(case / 'result.json', entry)
    return entry


def replay_panel(args):
    source = args.source_root.resolve(strict=True)
    campaign = args.campaign.resolve(strict=True)
    host = args.host_dll.resolve(strict=True)
    progress = args.progress_snapshot.resolve(strict=True)
    output = args.output.resolve()
    paths = sorted((campaign / 'cases').glob('*/result.json'))
    require(bool(paths), 'No source campaign results')
    runtime = json.loads(args.runtime_template.read_text())
    plan = campaign / 'plan.json'
    evidence = dict(host=identity(host), plan=identity(plan), sourceResults=[identity(p) for p in paths],
                    runtime=identity(args.runtime_template), progress=identity(progress), script=identity(__file__))
    write(output / 'launch.json', dict(pid=os.getpid(), startedAt=time.time(), workers=args.workers,
                                     productionDeployed=False, **evidence))
    os.environ['TMPDIR'] = str(output)
    counts = {}; checkpoints = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(replay_case, p, output, host, runtime, progress) for p in paths}
        while pending:
            done, pending = concurrent.futures.wait(pending, timeout=10,
                return_when=concurrent.futures.FIRST_COMPLETED)
            for future in done:
                entry = future.result()
                status = 'matched' if entry['passed'] else entry['failureStage']
                counts[status] = counts.get(status, 0) + 1
                checkpoints += entry.get('checkpoints', 0) if entry['passed'] else 0
            write(output / 'status.json', dict(updated=time.time(), counts=counts, checkpoints=checkpoints,
                    finished=sum(counts.values()), total=len(paths), productionDeployed=False))
    require(identity(host) == evidence['host'], 'Host changed during validation')
    require(identity(plan) == evidence['plan'], 'Plan changed during validation')
    require([identity(p) for p in paths] == evidence['sourceResults'], 'Original results changed during validation')
    # Independently revisit every full state, terminal, frozen build and emitted
    # native event, rather than trusting worker status flags or summary counts.
    from audit_build_panel import audit
    report = audit(source, output, plan, host, 500000)
    require(len(report['runs']) + len(report['nativeCaptureFailures'])
            + len(report['unresolvedReplayDifferences']) + len(report['staleHostResults']) == len(paths),
            'Final audit omitted a source case')
    write(output / 'final-audit.json', report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('runs', 'actualPlayedCards',
          'newActuallyPlayedCards', 'nativeCaptureFailures', 'unresolvedReplayDifferences', 'staleHostResults')}), flush=True)
    if not report['passed']:
        raise SystemExit(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('source-root', 'campaign', 'host-dll', 'runtime-template', 'progress-snapshot', 'output'):
        parser.add_argument('--' + name, required=True, type=Path)
    parser.add_argument('--workers', type=int, default=24, choices=range(1, 33))
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    # Keep the controller lock until every replay subprocess has drained. A
    # separate final audit can then prove drain using the existing audit CLI.
    with (output / 'batch.lock').open('x') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        setup = args.campaign.resolve(strict=True) / 'setup.json'
        write(output / 'setup.json', json.loads(setup.read_text()))
        write(output / 'capture-source-setup.json', identity(setup))
        replay_panel(args)


if __name__ == '__main__':
    main()
