"""Collect with the standalone simulator and the existing three task queues."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

from damage_model.provenance import sha256, teacher_for, verify_runtime
from tools.collect_continuous import Controller, atomic_json, exclusive

ROOT = Path(__file__).resolve().parents[1]


def load_bundle(bundle):
    """Read a frozen simulator release without importing its Python modules."""
    bundle = Path(bundle).resolve(strict=True)
    manifest = json.loads((bundle / 'release.json').read_text(encoding='utf-8'))
    if manifest.get('schema') != 'standalone-collector-release/v1':
        raise ValueError('Unsupported simulator release')
    required = {'teacher.json', 'runtime-template.json', 'host/SimulatorPrototype.dll',
                'host/SimulatorPrototype.runtimeconfig.json', 'host/SimulatorPrototype.deps.json',
                'progress-snapshot.json', 'catalogs/game-0.111.0.raw.json',
                'configs/real-runs-8s.json', 'configs/mutations-8s.json',
                'configs/mutations-targeted-8s.json'}
    if not required <= manifest['files'].keys():
        raise ValueError('Simulator release is missing pinned collection inputs')
    for name, expected in manifest['files'].items():
        path = (bundle / name).resolve(strict=True)
        if not path.is_relative_to(bundle) or sha256(path) != expected:
            raise ValueError('Simulator release file changed: ' + name)
    teacher = json.loads((bundle / 'teacher.json').read_text(encoding='utf-8'))
    runtime = json.loads((bundle / 'runtime-template.json').read_text(encoding='utf-8'))
    if (teacher != manifest['teacher']
            or runtime.get('backend') != 'standalone-managed-native'
            or teacher.get('execution_backend') != runtime['backend']):
        raise ValueError('Simulator release teacher/backend mismatch')
    runtime.update(host_dll=str(bundle / 'host/SimulatorPrototype.dll'),
                   progress_snapshot=str(bundle / 'progress-snapshot.json'))
    verify_runtime(runtime, teacher)
    return bundle, runtime


def prepare(bundle, directory, workers=1):
    if type(workers) is not int or workers < 1:
        raise ValueError('Simulator worker count must be positive')
    bundle, template = load_bundle(bundle)
    directory = Path(directory).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    session_path = directory / 'simulator-session.json'
    identity = {'bundle': str(bundle), 'release_sha256': sha256(bundle / 'release.json'),
                'workers': workers}
    session = json.loads(session_path.read_text()) if session_path.exists() else None
    if session is not None and session != identity:
        raise ValueError('Simulator release or worker count changed; use a new collection directory')
    if session is None and any(directory.iterdir()):
        raise ValueError('Use an empty simulator directory or an existing simulator session')
    runtimes = []
    for index in range(workers):
        data_dir = directory / f'worker-{index + 1:02d}'
        data_dir.mkdir(exist_ok=True)
        temporary = data_dir / 'tmp'
        temporary.mkdir(exist_ok=True)
        runtime = {**template, 'data_dir': str(data_dir),
                   'log_path': str(directory / 'logs' / f'simulator-{index + 1:02d}.log'),
                   'env': {**template.get('env', {}), 'TMPDIR': str(temporary)}}
        path = directory / f'runtime-{index + 1:02d}.json'
        if session is not None:
            if json.loads(path.read_text()) != runtime:
                raise ValueError('Simulator runtime changed: ' + str(path))
        else:
            atomic_json(path, runtime)
        runtimes.append(str(path))
    paths = {key: str(directory / 'db' / (name + '.sqlite')) for key, name in
             (('active_db', 'real'), ('mutation_db', 'mutations'), ('targeted_db', 'targeted'))}
    pointer = directory / 'active-collection.json'
    if session is not None:
        if json.loads(pointer.read_text()) != paths:
            raise ValueError('Simulator active database pointer changed')
    else:
        atomic_json(pointer, paths)
        atomic_json(session_path, identity)
    (directory / 'db').mkdir(exist_ok=True)
    return argparse.Namespace(
        db=paths['active_db'], mutation_db=paths['mutation_db'], targeted_db=paths['targeted_db'],
        config=str(bundle / 'configs/real-runs-8s.json'), teacher=str(bundle / 'teacher.json'),
        catalog=str(bundle / 'catalogs/game-0.111.0.raw.json'),
        mutation_policy=str(bundle / 'configs/mutations-8s.json'), mutation_workers=0,
        targeted_policy=str(bundle / 'configs/mutations-targeted-8s.json'),
        source_dir=str(directory / 'source/live'), source_start='2026-09-05T00:00:00Z',
        backfill_dir=str(directory / 'source/backfill'), queue_high_water=12000,
        active_pointer=str(pointer), runtimes=runtimes, reserve_gib=0, worker_start_gib=2,
        initial_samples=6080, initial_output=str(directory / 'checkpoints/v1'),
        output_root=str(directory / 'checkpoints/continuous'), poll_seconds=15,
        collect_only=True, stop_at=None)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path,
                        help='Frozen simulator release; defaults to STS2_SIMULATOR_BUNDLE or configs/simulator.json')
    parser.add_argument('--directory', type=Path, default=ROOT / '.local/simulator-collect')
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--limit', type=int, default=1, help='Battles per worker in a single pass')
    parser.add_argument('--import-runs', type=Path, help='Import local .run files instead of fetching public runs')
    parser.add_argument('--continuous', action='store_true', help='Continue collecting until stopped')
    options = parser.parse_args(argv)
    if options.limit < 1 or (options.continuous and options.import_runs):
        parser.error('Use a positive limit; --import-runs is for single passes')
    bundle = options.bundle or os.environ.get('STS2_SIMULATOR_BUNDLE')
    if bundle is None:
        bundle = json.loads((ROOT / 'configs/simulator.json').read_text())['bundle']
    options.directory = options.directory.resolve()
    if options.import_runs:
        options.import_runs = options.import_runs.resolve(strict=True)
    args = prepare(bundle, options.directory, options.workers)
    # Relative failure-evidence and log paths are private to this instance.
    previous = Path.cwd()
    previous_pythonpath = os.environ.get('PYTHONPATH')
    os.environ['PYTHONPATH'] = str(ROOT) + (os.pathsep + previous_pythonpath if previous_pythonpath else '')
    os.chdir(options.directory)
    controller = None
    try:
        with exclusive(Path(args.db).with_suffix('.continuous.lock')) as acquired:
            if not acquired:
                raise RuntimeError('Another controller owns this simulator collection')
            controller = Controller(args)
            print(json.dumps({'backend': 'standalone-managed-native', 'directory': str(Path.cwd()),
                              'teacher': args.teacher, 'runtimes': args.runtimes}), flush=True)
            def stop(signum, frame):
                controller.stop_requested = True
                for runtime_path in args.runtimes:
                    runtime = json.loads(Path(runtime_path).read_text())
                    (Path(runtime['data_dir']) / 'collector.stop').touch()
            handlers = {sig: signal.signal(sig, stop) for sig in (signal.SIGINT, signal.SIGTERM)}
            try:
                if options.continuous:
                    controller.run()
                else:
                    controller.guard()
                    if controller.stop_requested:
                        return
                    if options.import_runs:
                        from damage_model.run_import import import_files
                        import_files(controller.store, controller.catalog,
                                     teacher_for(controller.catalog, args.teacher), options.import_runs)
                    else:
                        controller.refill()
                    if controller.stop_requested:
                        return
                    subprocess.run([sys.executable, '-u', '-m', 'tools.collect_parallel',
                                '--db', args.db, '--config', args.config,
                                '--teacher', args.teacher, '--catalog', args.catalog,
                                '--fallback-db', args.mutation_db, '--targeted-db', args.targeted_db,
                                '--runtimes', *args.runtimes, '--limit-per-worker', str(options.limit),
                                '--reserve-gib', '0', '--worker-start-gib', '2'], check=True)
                    controller.refill_mutations()
                    print(json.dumps({'event': 'simulator_pass_complete',
                                      'counts': controller.work_counts()}), flush=True)
            finally:
                child = getattr(controller, 'child', None)
                if child is not None and child.poll() is None:
                    # Keep controller ownership until its pool has drained.
                    for runtime_path in args.runtimes:
                        runtime = json.loads(Path(runtime_path).read_text())
                        (Path(runtime['data_dir']) / 'collector.stop').touch()
                    while child.poll() is None:
                        try:
                            child.wait(timeout=1)
                        except subprocess.TimeoutExpired:
                            pass
                for sig, handler in handlers.items():
                    signal.signal(sig, handler)
    finally:
        if controller is not None:
            for store in (controller.store, controller.mutation_store, controller.targeted_store):
                if store is not None:
                    store.db.close()
        os.chdir(previous)
        if previous_pythonpath is None:
            os.environ.pop('PYTHONPATH', None)
        else:
            os.environ['PYTHONPATH'] = previous_pythonpath


if __name__ == '__main__':
    main()
