"""Own formal collection, native audit, backups and their complete drain lifecycle.

The deployment entry point supplies verified activation and local backup actions;
this module never grants acceptance or changes an active pointer on its own.
"""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import json
import os
from pathlib import Path
import shutil
import signal
import statistics
import subprocess
import sys
import time

import psutil

from run_standalone_rollout import counts, owned_command
from standalone_production_guard import drain_spec, drain_state, health_error, stop_and_drain
from standalone_rollout_metrics import identity, read, resource_snapshot, write
from standalone_rollout_provenance import checked_identity, require


class RequestedStop(Exception):
    pass


def ready_for(process, path, **expected):
    if process.poll() is not None or not Path(path).exists(): return False
    value = read(path)
    require(value.get('pid') == process.pid and value.get('ready') is True
            and all(value.get(k) == v for k, v in expected.items()), 'Child readiness identity differs')
    return True


def supervise(instance, audit_folder, directory, *, activate, backup,
              started=None, interval=1, backup_interval=1800, drain_timeout=190):
    """Run until explicit stop or failure; activation follows audit and backup readiness.

    activate() must perform the already-authorized, verified handoff and return
    {activated: True, activePointer: identity(...)}. backup() saves all three queues
    and returns the existing backup_once receipts keyed real/mutation/targeted.
    """
    audit_folder, directory = Path(audit_folder).resolve(strict=True), Path(directory).resolve()
    require(not directory.exists(), 'Use a fresh production supervisor directory; diagnose prior attempts')
    require(instance == read(Path(instance['directory']) / 'preparation.json'), 'Instance preparation changed')
    checked_identity(instance['proposedPointer'])
    spec = drain_spec(instance)
    require(drain_state(spec)['drained'], 'Prepared production instance is already owned or leased')
    require(not any(Path(p).exists() for p in [spec['controllerStop'], *spec['workerStops']]),
            'Existing collection stop markers require diagnosis')
    prepared_audit = read(audit_folder / 'preparation.json')
    checked_identity(prepared_audit['plan'])
    require(prepared_audit['plan'] == identity(audit_folder / 'plan.json')
            and read(audit_folder / 'plan.json')['instancePreparation']
            == identity(Path(instance['directory']) / 'preparation.json'), 'Audit instance differs')
    require(not any((audit_folder / name).exists() for name in ('audit-ready.json', 'audit-stop.json', 'audit-report.json')),
            'Audit already started or stopped; preserve its evidence')
    directory.mkdir(parents=True)
    write(directory / 'drain-spec.json', spec)
    before = resource_snapshot()
    initial_error = health_error(before, before, shutil.disk_usage(directory).free, {}, {}, auditor_alive=True)
    require(initial_error is None, initial_error)
    owner = dict(pid=os.getpid(), created=psutil.Process().create_time())
    write(directory / 'owner.json', owner)
    environment = {**os.environ, 'TMPDIR': str(Path(instance['directory'])),
                   'PYTHONDONTWRITEBYTECODE': '1', 'DISPLAY': '', 'WAYLAND_DISPLAY': ''}
    controller = auditor = watchdog = pending_backup = None
    activation = failure = None
    last_backup = None
    samples = []; next_counts = next_sample = 0; queued = {}; collection_started = None
    stopped = False
    original_handlers = {}

    def stop_signal(signum, frame):
        nonlocal stopped
        stopped = True

    def status(state, **extra):
        write(directory / 'status.json', dict(state=state, updated=time.time(),
              productionDeployed=activation is not None, controllerPid=controller.pid if controller else None,
              auditPid=auditor.pid if auditor else None, watchdogPid=watchdog.pid if watchdog else None, **extra))

    def backup_result(future):
        result = future.result()
        require(set(result) == {'real', 'mutation', 'targeted'}
                and all(value.get('state') == 'saved' for value in result.values()), 'Incomplete production backup')
        write(directory / 'latest-backups.json', result)
        return result

    with ExitStack() as files, ThreadPoolExecutor(max_workers=1) as executor:
        resources = files.enter_context((directory / 'resources.jsonl').open('x'))

        def launch(name, command, owned=True):
            log = files.enter_context((directory / (name + '.log')).open('x'))
            process = subprocess.Popen(owned_command(command) if owned else command,
                cwd=instance['cwd'], env=environment, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                write(directory / (name + '-owner.json'), dict(pid=process.pid,
                      created=psutil.Process(process.pid).create_time(), command=command))
            except BaseException:
                if process.poll() is None: process.send_signal(signal.SIGTERM)
                process.wait(timeout=190)
                raise
            return process

        def monitor(state):
            nonlocal next_counts, next_sample, queued
            now = time.monotonic()
            if stopped or (directory / 'STOP').exists(): raise RequestedStop('Explicit production stop')
            require(watchdog.poll() is None, 'Parent-death watchdog exited')
            require(not (audit_folder / 'audit-stop.json').exists(), 'Native audit requested collection drain')
            if controller is not None: require(controller.poll() is None, 'Collection controller exited unexpectedly')
            if activation is not None: checked_identity(activation['activePointer'])
            if now >= next_counts:
                queued = counts([Path(p) for p in spec['queues']]); next_counts = now + 15
            current = resource_snapshot()
            audit_status = read(audit_folder / 'audit-status.json') if (audit_folder / 'audit-status.json').exists() else {}
            error = health_error(before, current, shutil.disk_usage(directory).free, queued, audit_status,
                                 auditor_alive=auditor.poll() is None)
            require(error is None, error)
            if now >= next_sample:
                worker_rss = 0
                if controller is not None:
                    try:
                        for child in psutil.Process(controller.pid).children(recursive=True):
                            try:
                                if 'damage_model.cli' in child.cmdline(): worker_rss += child.memory_info().rss
                            except psutil.NoSuchProcess: pass
                    except psutil.NoSuchProcess: pass
                current['workerRssBytes'] = worker_rss
                resources.write(json.dumps(current) + '\n'); resources.flush()
                if collection_started is not None and now - collection_started > len(spec['workerStops']) * 2 + 30 and worker_rss:
                    # Fixed first window and bounded recent window: sustained growth
                    # uses the same 128 MiB / 50% allowance as acceptance.
                    samples.append(worker_rss)
                    if len(samples) > 120: del samples[60]
                    if len(samples) == 120:
                        early, late = statistics.median(samples[:60]), statistics.median(samples[-60:])
                        require(late <= early + max(128 * 2**20, early * .5), 'Sustained production worker memory growth')
                status(state, counts=queued, audit=audit_status, resources=current,
                       lastBackupAt=max((v['updated'] for v in last_backup.values()), default=None) if last_backup else None)
                next_sample = now + 5

        try:
            for sig in (signal.SIGINT, signal.SIGTERM):
                original_handlers[sig] = signal.signal(sig, stop_signal)
            watchdog = launch('watchdog', [sys.executable, str(Path(__file__).with_name('standalone_production_guard.py')),
                '--spec', str(directory / 'drain-spec.json'), '--parent', str(owner['pid']),
                '--parent-created', str(owner['created']), '--ready', str(directory / 'watchdog-ready.json')], owned=False)
            auditor = launch('audit', prepared_audit['command'])
            pending_backup = executor.submit(backup)
            next_backup = time.monotonic() + backup_interval
            while True:
                monitor('preparing_collection')
                if pending_backup is not None and pending_backup.done():
                    last_backup = backup_result(pending_backup); pending_backup = None
                if (last_backup is not None
                    and ready_for(watchdog, directory / 'watchdog-ready.json', parent=owner['pid'], parentCreated=owner['created'])
                    and ready_for(auditor, audit_folder / 'audit-ready.json', productionAudit=True, plan=prepared_audit['plan'])):
                    break
                time.sleep(interval)
            activation = activate()
            require(activation.get('activated') is True, 'Deployment did not activate the prepared instance')
            checked_identity(activation['activePointer'])
            require(read(activation['activePointer']['path']) == read(instance['proposedPointer']['path']),
                    'Activated pointer differs from prepared instance')
            write(directory / 'activation.json', activation)
            monitor('starting_collection')
            controller = launch('controller', instance['command'])
            collection_started = time.monotonic()
            if started is not None: started(controller)
            status('collecting', activation=activation)
            while True:
                monitor('collecting')
                if pending_backup is not None and pending_backup.done():
                    last_backup = backup_result(pending_backup); pending_backup = None
                if time.monotonic() >= next_backup and pending_backup is None:
                    pending_backup = executor.submit(backup); next_backup = time.monotonic() + backup_interval
                time.sleep(interval)
        except RequestedStop:
            status('stopping', reason='Explicit production stop')
        except BaseException as error:
            failure = error
            status('stopping', error=repr(error))
        finally:
            # No second signal may skip cleanup. SIGKILL remains covered by watchdog.
            for sig in original_handlers: signal.signal(sig, stop_signal)
            drain = None
            try:
                drain = stop_and_drain(spec, controller, directory / 'drain.json', timeout=drain_timeout)
            except BaseException as error:
                if failure is None: failure = error
                write(directory / 'drain-error.json', dict(error=repr(error), updated=time.time()))
            if auditor is not None:
                try:
                    if failure is None and drain and drain['drained'] and controller is not None:
                        write(audit_folder / 'collection-drained.json', dict(complete=True, drain=identity(directory / 'drain.json')))
                        while auditor.poll() is None:
                            status('finishing_audit'); time.sleep(interval)
                        require(auditor.returncode == 0 and read(audit_folder / 'audit-report.json')['passed'],
                                'Final production audit did not pass')
                    else:
                        if auditor.poll() is None: auditor.send_signal(signal.SIGTERM)
                        auditor.wait(timeout=190)
                except BaseException as error:
                    if failure is None: failure = error
                    write(directory / 'audit-drain-error.json', dict(error=repr(error), updated=time.time()))
            if watchdog is not None:
                try:
                    if watchdog.poll() is None: watchdog.send_signal(signal.SIGTERM)
                    watchdog.wait(timeout=10)
                except BaseException as error:
                    if failure is None: failure = error
            if pending_backup is not None:
                try:
                    while not pending_backup.done():
                        status('finishing_backup', error=repr(failure) if failure else None); time.sleep(interval)
                    last_backup = backup_result(pending_backup)
                except BaseException as error:
                    if failure is None: failure = error
            if failure is None and controller is not None and drain and drain['drained']:
                try:
                    final_backup = executor.submit(backup)
                    while not final_backup.done():
                        status('final_backup'); time.sleep(interval)
                    last_backup = backup_result(final_backup)
                except BaseException as error:
                    failure = error
            status('failed' if failure else 'paused', error=repr(failure) if failure else None, drain=drain)
            for sig, handler in original_handlers.items(): signal.signal(sig, handler)
    if failure is not None: raise failure
    return read(directory / 'status.json')
