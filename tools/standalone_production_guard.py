"""Production health checks and bounded drain, including supervisor death."""
import argparse
from contextlib import ExitStack, closing
import ctypes
import fcntl
import json
import os
from pathlib import Path
import signal
import sqlite3
import time

import psutil

from standalone_rollout_metrics import read, write
from standalone_rollout_provenance import checked_identity, require


def drain_spec(instance):
    """Freeze stop/lock paths before a mutable live session can be updated."""
    checked_identity(instance['session'])
    session = read(instance['session']['path'])
    directory = Path(instance['directory']).resolve(strict=True)
    queues = [Path(session[key]).resolve(strict=True) for key in ('active_db', 'mutation_db', 'targeted_db')]
    require(len(set(queues)) == 3, 'Production queues overlap')
    require(all(path.parent == directory.parent for path in queues), 'Queue outside prepared handoff')
    workers = []
    for entry in instance['runtimes']:
        checked_identity(entry)
        data = Path(read(entry['path'])['data_dir']).resolve(strict=True)
        require(data.is_relative_to(directory / 'workers'), 'Worker outside prepared instance')
        workers.append(data)
    require(len(workers) == len(set(workers)) == session['workers'] > 0, 'Worker directory or count differs')
    return dict(queues=list(map(str, queues)), controllerStop=str(queues[0].with_suffix('.continuous.stop')),
        workerStops=[str(path / 'collector.stop') for path in workers],
        lockPaths=[str(queues[0].with_suffix('.continuous.lock')),
                   *[str(path.with_suffix('.pool.lock')) for path in queues],
                   *[str(path / 'collector.lock') for path in workers]])


def request_stop(spec):
    # Stop new controller launches before telling workers to finish in-flight work.
    for name in [spec['controllerStop'], *spec['workerStops']]:
        Path(name).touch()


def drain_state(spec):
    """Check every ownership lock together; no expired lease is stolen here."""
    with ExitStack() as stack:
        for name in spec['lockPaths']:
            lock = stack.enter_context(Path(name).open('a+'))
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                return dict(drained=False, busyLock=name)
        running = {}
        for name in spec['queues']:
            path = Path(name).resolve(strict=True)
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as db:
                running[name] = db.execute("SELECT count(*) FROM jobs WHERE status='running'").fetchone()[0]
        return dict(drained=not any(running.values()), running=running)


def stop_and_drain(spec, controller, report, timeout=190):
    """Signal only the owned Popen; wait for its separately spawned pool/worker locks."""
    request_stop(spec)
    if controller is not None and controller.poll() is None:
        controller.send_signal(signal.SIGTERM)
    deadline = time.monotonic() + timeout
    while True:
        state = drain_state(spec)
        exited = controller is None or controller.poll() is not None
        state.update(controllerExited=exited, controllerExitCode=controller.returncode if controller is not None else None,
                     updated=time.time())
        state['drained'] = state['drained'] and exited
        write(report, state)
        if state['drained']:
            return state
        if time.monotonic() >= deadline:
            raise TimeoutError('Production did not drain; preserve owners, leases and stop markers: ' + str(report))
        time.sleep(min(1, max(0, deadline - time.monotonic())))


def health_error(before, current, disk_free, counts, audit_status, *, auditor_alive, backup_error=None):
    """Reuse acceptance bounds during formal collection; return a stop reason."""
    if not auditor_alive: return 'Native audit process exited'
    if backup_error is not None: return 'Production backup failed: ' + str(backup_error)
    if current['availableBytes'] < 16 * 2**30: return 'Effective memory reserve below 16 GiB'
    if disk_free < 50 * 2**30: return 'Evidence disk reserve below 50 GiB'
    if current['cpuQuotaCores'] < before['cpuQuotaCores']: return 'CPU quota fell below calibrated deployment capacity'
    previous = {item['path']: item for item in before['cgroups']}
    now = {item['path']: item for item in current['cgroups']}
    if previous.keys() != now.keys(): return 'Resource cgroup hierarchy changed'
    for path in previous:
        old = dict(line.split() for line in previous[path].get('memory.events', '').splitlines())
        new = dict(line.split() for line in now[path].get('memory.events', '').splitlines())
        if int(new.get('oom_kill', 0)) > int(old.get('oom_kill', 0)): return 'OOM kill observed in deployment cgroup'
    if counts.get('failed', 0): return 'Production queue contains failed jobs'
    quarantined = counts.get('quarantined', 0)
    if quarantined / max(1, counts.get('complete', 0) + quarantined) > .01:
        return 'More than 1% of settled production jobs quarantined'
    audit_counts = audit_status.get('counts', {})
    if audit_counts.get('mismatch') or audit_counts.get('native_failed'):
        return 'Selected production audit has a failed sample'
    return None


def watch_parent(spec_path, parent, created, ready):
    """Parent-death signal writes worker stop markers even if controller already exits."""
    spec = read(spec_path)
    def stop(signum, frame):
        request_stop(spec)
        write(Path(ready).with_name('watchdog-stopped.json'),
              dict(parent=parent, parentCreated=created, signal=signum, updated=time.time()))
        raise SystemExit(0)
    for sig in (signal.SIGTERM, signal.SIGINT): signal.signal(sig, stop)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGTERM, 0, 0, 0):
        raise OSError(ctypes.get_errno(), 'Cannot arm production parent-death drain')
    # Handle parent death between spawn and prctl; a reused PID cannot take over.
    if os.getppid() != parent:
        stop(0, None)
    try:
        same = psutil.Process(parent).create_time() == created
    except psutil.NoSuchProcess:
        same = False
    if not same: stop(0, None)
    write(ready, dict(ready=True, pid=os.getpid(), parent=parent, parentCreated=created, updated=time.time()))
    while True: signal.pause()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Production parent-death watchdog (supervisor internal helper)')
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--parent', type=int, required=True)
    parser.add_argument('--parent-created', type=float, required=True)
    parser.add_argument('--ready', type=Path, required=True)
    args = parser.parse_args()
    watch_parent(args.spec, args.parent, args.parent_created, args.ready)
