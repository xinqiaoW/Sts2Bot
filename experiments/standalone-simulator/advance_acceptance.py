#!/usr/bin/env python3
"""Advance one frozen validation through isolated rollout, preserving failures."""
import argparse
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import psutil


def owner_alive(pid, created):
    try:
        owner = psutil.Process(pid)
        if owner.create_time() != created:
            raise ValueError('Validation PID was reused; inspect ownership before proceeding')
        return owner.is_running() and owner.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def require_drained_summary(report):
    if (report.get('requestedComparisonPassed') is not True
            or not report.get('workerExitCodes')
            or any(code != 0 for code in report['workerExitCodes'])
            or report.get('validatedBuildCount', 0) < 10000
            or report.get('validatedTargetCount') != 80
            or report.get('totalCheckpoints', 0) < 500000
            or report.get('unresolvedReplayDifferences') != 0):
        raise ValueError('Validation did not finish with the required counts and all workers drained')


def execute_stage(name, command, folder, write, owned_command):
    """Fresh output only; interrupted stages require diagnosis, never a retry."""
    receipt = dict(stage=name, command=command, startedAt=time.time())
    stop = folder / 'STOP'
    if stop.exists():
        raise RuntimeError('Explicit acceptance stop marker')
    with (folder / (name + '.log')).open('x') as log:
        process = subprocess.Popen(owned_command(command), stdout=log, stderr=subprocess.STDOUT,
                                   cwd=folder, env={**os.environ, 'TMPDIR': str(folder),
                                   'DISPLAY': '', 'WAYLAND_DISPLAY': '', 'PYTHONDONTWRITEBYTECODE': '1'},
                                   start_new_session=True)
        receipt.update(pid=process.pid, created=psutil.Process(process.pid).create_time())
        write(folder / (name + '-launch.json'), receipt)
        print(json.dumps({'stage': name, 'pid': process.pid}), flush=True)
        try:
            while process.poll() is None:
                write(folder / 'status.json', {**receipt, 'state': 'running', 'updated': time.time(),
                                              'productionDeployed': False})
                if stop.exists():
                    raise RuntimeError('Explicit acceptance stop marker')
                time.sleep(5)
        except BaseException:
            if process.poll() is None:
                process.send_signal(signal.SIGTERM)
                process.wait(timeout=240)
            raise
    receipt.update(exitCode=process.returncode, finishedAt=time.time())
    write(folder / (name + '-exit.json'), receipt)
    if process.returncode:
        raise RuntimeError(f'{name} failed with exit code {process.returncode}; original logs retained')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation', type=Path, required=True)
    parser.add_argument('--validation-pid', type=int, required=True)
    parser.add_argument('--validation-created', type=float, required=True)
    parser.add_argument('--directory', type=Path, required=True)
    args = parser.parse_args()
    preparation = json.loads(args.preparation.read_text())
    root = args.preparation.resolve().parent
    source = root / 'preparation-source-v2'
    auditor = root / 'independent-auditor-v2'
    sys.path.insert(0, str(source / 'tools'))
    from standalone_rollout_metrics import identity, read, sha, write
    from standalone_rollout_provenance import checked_identity, verify_correctness, verify_benchmark
    from run_standalone_rollout import owned_command
    folder = args.directory.resolve(); folder.mkdir()
    def interrupted(signum, frame):
        raise KeyboardInterrupt('Acceptance controller interrupted')
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, interrupted)
    with (folder / 'controller.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        write(folder / 'owner.json', dict(pid=os.getpid(), created=psutil.Process().create_time(),
              preparation=identity(args.preparation), script=identity(__file__),
              validationPid=args.validation_pid, validationCreated=args.validation_created))
        try:
            for name, expected in preparation['sourceFiles'].items():
                if sha(source / name) != expected: raise ValueError('Preparation source changed: ' + name)
            for name, expected in preparation['auditorFiles'].items():
                if sha(auditor / name) != expected: raise ValueError('Independent auditor changed: ' + name)
            for key in ('releaseManifest', 'nativeRuntime', 'sourceDatabase', 'rolloutSource'):
                checked_identity(preparation[key])
            bundle = Path(preparation['candidateRelease'])
            spec = importlib.util.spec_from_file_location('candidate_release', bundle / 'release_tool.py')
            release = importlib.util.module_from_spec(spec); spec.loader.exec_module(release)
            release.verify(bundle)
            audit_command = preparation['finalAuditCommand']
            campaign = Path(audit_command[audit_command.index('--directory') + 1])
            report_path = campaign / 'full-report.json'
            # Never infer process death from old status text or an observation timeout.
            while owner_alive(args.validation_pid, args.validation_created):
                report = read(report_path)
                write(folder / 'status.json', dict(state='waiting_for_validation', updated=time.time(),
                      validationPid=args.validation_pid, finished=report['finishedCases'],
                      matched=report['matchedCases'], checkpoints=report['totalCheckpoints'],
                      differences=report['unresolvedReplayDifferences'], productionDeployed=False))
                if (folder / 'STOP').exists(): raise RuntimeError('Explicit acceptance stop marker')
                time.sleep(15)
            require_drained_summary(read(report_path))
            execute_stage('independent-audit', audit_command, folder, write, owned_command)
            audit_path = Path(audit_command[audit_command.index('--output') + 1])
            accepted = verify_correctness(audit_path, bundle, campaign / 'plan.json')
            execute_stage('paired-performance', preparation['benchmarkCommand'], folder, write, owned_command)
            command = preparation['benchmarkCommand']
            benchmark = Path(command[command.index('--report') + 1])
            verify_benchmark(identity(benchmark), accepted)
            execute_stage('prepare-rollout', preparation['prepareRolloutCommand'], folder, write, owned_command)
            execute_stage('isolated-rollout', preparation['rolloutCommand'], folder, write, owned_command)
            command = preparation['rolloutCommand']; rollout = Path(command[command.index('--directory') + 1])
            final = read(rollout / 'final-report.json')
            if final.get('passed') is not True:
                raise ValueError('Isolated rollout did not pass all gates')
            write(folder / 'status.json', dict(state='ready_for_formal_handoff', updated=time.time(),
                  finalReport=identity(rollout / 'final-report.json'), productionDeployed=False))
        except BaseException as error:
            write(folder / 'status.json', dict(state='failed', updated=time.time(), error=repr(error),
                                              productionDeployed=False))
            raise


if __name__ == '__main__':
    main()
