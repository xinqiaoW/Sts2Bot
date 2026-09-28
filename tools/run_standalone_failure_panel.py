"""Diagnose every quarantined request without publishing labels or changing queues.

An original successful recording is always reused, even if its replay failed.
All cases are inspected after a mismatch; failures remain failures in the report.
"""
import argparse
import concurrent.futures
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'experiments/standalone-simulator'))
from replay_evidence import identity, normalized, terminal, validate_replay, write
from standalone_rollout_audit import isolated_native, replay_fixture


def prior_recordings(campaign):
    records = {}
    for request_path in sorted((campaign / 'quarantine-audit').glob('case-*/request.json')):
        request = json.loads(request_path.read_text())
        records[request['sourceJobId']] = sorted(request_path.parent.glob('native-*.json'))
    return records


def validate_native(native, entry, plan, progress):
    if normalized(native['request']) != normalized(entry['request']):
        raise ValueError('Recording changed the requested input')
    if native['progressSnapshotSha256'] != identity(progress)['sha256']:
        raise ValueError('Recording progress differs')
    if native['traceModSha256'] != plan['traceDll']['sha256']:
        raise ValueError('Recording observer differs')
    if native['complete']:
        trace = Path(native['directory']) / (native['request']['runId'] + '.jsonl')
        if [json.loads(line) for line in trace.read_text().splitlines()] != native['events']:
            raise ValueError('Raw native trace differs from recording')


def diagnose_group(number, entries, campaign, output, host):
    plan = json.loads((campaign / 'plan.json').read_text())
    source = Path(plan['nativeSource'])
    sys.path.insert(0, str(source))
    sys.path.insert(0, str(source / 'experiments/native-trace-probe'))
    from persistent_capture_v2 import PersistentCapture
    bundle = Path(plan['bundle'])
    progress = bundle / 'progress-snapshot.json'
    runtime = json.loads((bundle / 'runtime-template.json').read_text())
    previous = prior_recordings(campaign)
    native_dir = output / f'worker-{number:02}'
    native_dir.mkdir()
    capture = None
    try:
        for index, entry in entries:
            case = output / f'case-{index:06}'
            case.mkdir()
            request_path = case / 'request.json'
            write(request_path, entry)
            receipt = dict(caseId=index, job=entry['job'], build=entry['build'],
                           target=entry['target'], dataset=entry['dataset'],
                           status='error', nativeAttempts=[], host=identity(host))
            try:
                native = None
                for raw in previous.get(entry['job'], []):
                    recorded = json.loads(raw.read_text())
                    validate_native(recorded, entry, plan, progress)
                    receipt['nativeAttempts'].append(identity(raw))
                    if recorded['complete']:
                        native = recorded
                        break
                # Retry only incomplete captures, up to three attempts including
                # prior evidence. Never replace an inconvenient successful trace.
                while native is None and len(receipt['nativeAttempts']) < 3:
                    if capture is None:
                        native_runtime = isolated_native(plan, native_dir)
                        capture = PersistentCapture(native_dir, native_runtime, progress, plan['traceDll']['path'])
                    attempt = len(receipt['nativeAttempts']) + 1
                    raw, log = case / f'native-{attempt}.json', case / f'native-{attempt}.log'
                    capture.capture(request_path, raw, log)
                    recorded = json.loads(raw.read_text())
                    validate_native(recorded, entry, plan, progress)
                    receipt['nativeAttempts'].append(identity(raw))
                    if recorded['complete']:
                        native = recorded
                receipt['status'] = 'native_failed'
                if native is not None:
                    fixture, log = case / 'replay.json', case / 'replay.log'
                    write(fixture, replay_fixture(native, entry['job'], entry['build']))
                    command = [runtime['dotnet'], str(host), runtime['game_dir'],
                               '--replay-native-request', str(fixture), str(progress)]
                    receipt['command'] = command
                    try:
                        with log.open('x') as stream:
                            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT,
                                env=dict(os.environ, DOTNET_PROCESSOR_COUNT='1', DOTNET_TieredCompilation='0'), timeout=120)
                        receipt['exitCode'] = result.returncode
                        if result.returncode:
                            raise ValueError('Replay host failed')
                        receipt.update(validate_replay(native, terminal(log)))
                        receipt['status'] = 'matched'
                    except (ValueError, AssertionError, subprocess.TimeoutExpired) as error:
                        receipt.update(status='mismatch', error=str(error))
                    receipt.update(fixture=identity(fixture), replay=identity(log))
            except Exception:
                receipt.update(status='error', error=traceback.format_exc())
            write(case / 'result.json', receipt)
            print(json.dumps(dict(caseId=index, status=receipt['status'], target=entry['target'])), flush=True)
    finally:
        if capture is not None:
            capture.close()


def summarize(output, total):
    results = [json.loads(p.read_text()) for p in sorted(output.glob('case-*/result.json'))]
    counts = {}
    for result in results:
        counts[result['status']] = counts.get(result['status'], 0) + 1
    return dict(updated=time.time(), total=total, finished=len(results), counts=counts,
                checkpoints=sum(r.get('checkpoints', 0) for r in results),
                passed=len(results) == total and counts.get('matched') == total,
                productionDeployed=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign', type=Path, required=True)
    parser.add_argument('--host', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=4, choices=range(1, 9))
    args = parser.parse_args()
    campaign = args.campaign.resolve(strict=True)
    host = args.host.resolve(strict=True)
    plan = json.loads((campaign / 'plan.json').read_text())
    panel_path = Path(plan['quarantineInputs']['path'])
    if identity(panel_path) != plan['quarantineInputs']:
        raise ValueError('Pinned quarantine panel changed')
    for name, digest in plan['nativeFiles'].items():
        if identity(Path(plan['nativeSource']) / name)['sha256'] != digest:
            raise ValueError('Native recorder source changed: ' + name)
    if identity(plan['traceDll']['path']) != plan['traceDll']:
        raise ValueError('Native observer changed')
    panel = json.loads(panel_path.read_text())
    if not panel or len({r['job'] for r in panel}) != len(panel):
        raise ValueError('Empty or duplicate failure panel')
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    write(output / 'launch.json', dict(pid=os.getpid(), startedAt=time.time(), host=identity(host),
          campaign=identity(campaign / 'plan.json'), panel=identity(panel_path), workers=args.workers,
          script=identity(__file__), productionDeployed=False))
    os.environ['STS2_NATIVE_STARTUP_LOCK_DIR'] = str(output / 'startup-locks')
    os.environ['STS2_NATIVE_STARTUP_SLOTS'] = str(args.workers)
    os.environ['TMPDIR'] = str(output)
    indexed = list(enumerate(panel, 1))
    try:
        with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers) as pool:
            pending = {pool.submit(diagnose_group, i, indexed[i::args.workers], campaign, output, host)
                       for i in range(args.workers)}
            while pending:
                done, pending = concurrent.futures.wait(pending, timeout=10,
                    return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    future.result()
                write(output / 'status.json', summarize(output, len(panel)))
        summary = summarize(output, len(panel))
        summary['cases'] = [identity(p) for p in sorted(output.glob('case-*/result.json'))]
        write(output / 'report.json', summary)
    except BaseException:
        write(output / 'controller-error.json', dict(error=traceback.format_exc(), **summarize(output, len(panel))))
        raise


if __name__ == '__main__':
    main()
