"""Adopt the ready real queue, then switch 25 workers to all prepared sources."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from damage_model.store import Store
from tools.collect_parallel import validate_runtimes


def validate_ready(report, counts):
    if (not report['apply'] or len(report['sources']) != 3
            or report['jobs_added'] != report['jobs_to_add']):
        raise ValueError('Queue preparation is incomplete')
    expected = [s['expected_output_jobs'] for s in report['sources']]
    if any(s['expected_output_jobs'] != s['existing_output_jobs'] + s['jobs_to_add']
           for s in report['sources']) or sum(s['jobs_to_add'] for s in report['sources']) != report['jobs_added']:
        raise ValueError('Prepared queue counts do not reconcile')
    if len(counts) != 3:
        raise ValueError('All three queues are required')
    for value, expected_count in zip(counts, expected):
        if sum(value.values()) != expected_count or value.get('failed', 0):
            raise ValueError('Incomplete queue or failed samples require diagnosis')


def require_not_stopped(root):
    if (root/'pipeline.stop').exists() or (root/'resource-guard-stop.json').exists():
        raise RuntimeError('Collection is stopped; do not resume automatically')


def active_process(pid, token):
    try:
        return token in Path(f'/proc/{pid}/cmdline').read_bytes()
    except FileNotFoundError:
        return False


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    args = parser.parse_args()
    root = Path(args.run_dir).resolve()

    def state(name, **fields):
        value = {'state': name, 'updated': time.time(), 'pid': os.getpid(), **fields}
        path = root/'pipeline-state.json'
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(value, indent=2))
        temporary.replace(path)
        print(json.dumps(value), flush=True)

    with (root/'pipeline.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            require_not_stopped(root)
            bootstrap = json.loads((root/'bootstrap-pool-process.json').read_text())
            prepare = json.loads((root/'prepare-process.json').read_text())
            state('collecting_ready_queue', pool_pid=bootstrap['pid'])
            while not (root/'prepare-report.json').exists():
                if (root/'pipeline.stop').exists():
                    state('switch_cancelled')
                    return
                if not active_process(bootstrap['pid'], b'tools.collect_parallel'):
                    raise RuntimeError('Ready-queue pool stopped; diagnose before switching')
                if not active_process(prepare['pid'], b'backfill_targeted_seeds'):
                    raise RuntimeError('Preparation stopped without a report; inspect prepare.log')
                time.sleep(5)
            # The report is emitted at the end; wait for its writer to close.
            while active_process(prepare['pid'], b'backfill_targeted_seeds'):
                require_not_stopped(root)
                time.sleep(1)
            if (root/'pipeline.stop').exists() or (root/'resource-guard-stop.json').exists():
                raise RuntimeError('Switch cancelled or resource protection triggered')
            report = json.loads((root/'prepare-report.json').read_text())
            paths = [Path(source['output']) for source in report['sources']]

            def counts():
                values = []
                for path in paths:
                    store = Store(path)
                    try:
                        values.append(store.counts())
                    finally:
                        store.db.close()
                return values

            validate_ready(report, counts())
            require_not_stopped(root)
            if not active_process(bootstrap['pid'], b'tools.collect_parallel'):
                raise RuntimeError('Ready-queue pool stopped before the planned transition')
            state('draining_for_all_sources', pool_pid=bootstrap['pid'])
            os.kill(bootstrap['pid'], signal.SIGINT)
            deadline = time.monotonic()+240
            while active_process(bootstrap['pid'], b'tools.collect_parallel'):
                require_not_stopped(root)
                if time.monotonic() > deadline:
                    raise RuntimeError('Pool did not drain; preserve workers for diagnosis')
                time.sleep(1)
            status_path = paths[0].with_suffix('.parallel.json')
            (root/'bootstrap-final.parallel.json').write_bytes(status_path.read_bytes())
            final = counts()
            validate_ready(report, final)
            if any(value.get('running', 0) for value in final):
                raise RuntimeError('Running leases remain after drain')
            (root/'prepared-queue-counts.json').write_text(json.dumps(final, indent=2))
            runtimes = json.loads((root/'runtimes.json').read_text())
            if len(runtimes) != 25:
                raise ValueError('Exactly 25 workers are required')
            for config in validate_runtimes(runtimes):
                with (Path(config['data_dir'])/'collector.lock').open('a+') as runtime_lock:
                    fcntl.flock(runtime_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            command = [sys.executable, '-u', '-m', 'tools.collect_parallel', '--db', str(paths[0]),
                       '--config', 'configs/real-runs-8s.json', '--fallback-db', str(paths[1]),
                       '--targeted-db', str(paths[2]), '--runtimes', *runtimes, '--reserve-gib', '32',
                       '--worker-start-gib', '3', '--limit-per-worker', '6080', '--continuous-workers']
            require_not_stopped(root)
            with (root/'logs/pool.log').open('ab') as log:
                pool = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
            info = {'pid': pool.pid, 'command': command, 'started': time.time(), 'phase': 'all_three_queues'}
            (root/'pool-process.json').write_text(json.dumps(info, indent=2))
            with (root/'logs/resource-guard.log').open('ab') as log:
                guard = subprocess.Popen([sys.executable, str(root/'resource_guard.py')],
                                         stdout=log, stderr=log, start_new_session=True)
            (root/'resource-guard-process.json').write_text(json.dumps({'pid': guard.pid, 'started': time.time()}))
            state('starting_all_sources', pool_pid=pool.pid)
            deadline = time.monotonic()+900
            while time.monotonic() < deadline:
                if pool.poll() is not None:
                    raise RuntimeError('Full pool stopped during startup')
                status = json.loads(status_path.read_text())
                if status.get('pid') == pool.pid:
                    if status['state'] in ('failed', 'draining'):
                        raise RuntimeError('Full pool failed; inspect its original error')
                    if status['state'] == 'collecting' and status['workers'] == 25:
                        state('collecting_all_sources', pool_pid=pool.pid, counts=status['combined_counts'])
                        return
                time.sleep(5)
            raise RuntimeError('Full pool startup exceeded 15 minutes')
        except BaseException as error:
            state('needs_diagnosis', error=str(error))
            raise


if __name__ == '__main__':
    main()
