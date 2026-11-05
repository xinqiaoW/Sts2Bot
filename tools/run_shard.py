"""Independent runner for distributed simulation shards.

Runs worker pools against a self-contained shard SQLite database, cleanly
drains on stop signals, and supports resuming at any point.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def atomic_json(path: Path, value: dict):
    tmp = path.with_suffix(f'.tmp.{os.getpid()}')
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    tmp.replace(path)


def load_bundle(bundle_path: Path):
    bundle = Path(bundle_path).resolve(strict=True)
    manifest = json.loads((bundle / 'release.json').read_text(encoding='utf-8'))
    teacher = json.loads((bundle / 'teacher.json').read_text(encoding='utf-8'))
    template = json.loads((bundle / 'runtime-template.json').read_text(encoding='utf-8'))
    catalog = str(bundle / 'catalogs/game-0.111.0.raw.json')
    config = str(bundle / 'configs/real-runs-8s.json')
    return {
        'bundle': bundle,
        'manifest': manifest,
        'teacher': str(bundle / 'teacher.json'),
        'catalog': catalog,
        'config': config,
        'template': template,
        'host_dll': str(bundle / 'host/SimulatorPrototype.dll'),
        'progress_snapshot': str(bundle / 'progress-snapshot.json'),
    }


def prepare_runtimes(
    work_dir: Path,
    bundle_info: dict,
    workers: int,
    game_dir: str | None = None,
    dotnet: str | None = None,
) -> list[str]:
    work_dir.mkdir(parents=True, exist_ok=True)
    logs_dir = work_dir / 'logs'
    logs_dir.mkdir(exist_ok=True)

    template = dict(bundle_info['template'])
    if game_dir:
        template['game_dir'] = str(Path(game_dir).resolve(strict=True))
    if dotnet:
        template['dotnet'] = str(Path(dotnet).resolve(strict=True))
    template['host_dll'] = bundle_info['host_dll']
    template['progress_snapshot'] = bundle_info['progress_snapshot']

    runtime_paths = []
    for i in range(workers):
        worker_dir = work_dir / f'worker-{i + 1:02d}'
        worker_dir.mkdir(exist_ok=True)
        tmp_dir = worker_dir / 'tmp'
        tmp_dir.mkdir(exist_ok=True)

        worker_runtime = {
            **template,
            'data_dir': str(worker_dir),
            'log_path': str(logs_dir / f'simulator-{i + 1:02d}.log'),
            'env': {
                **template.get('env', {}),
                'TMPDIR': str(tmp_dir),
            },
        }
        r_path = work_dir / f'runtime-{i + 1:02d}.json'
        atomic_json(r_path, worker_runtime)
        runtime_paths.append(str(r_path))

    return runtime_paths


def query_db_counts(db_path: Path) -> dict[str, int]:
    import sqlite3
    try:
        con = sqlite3.connect(f'file:{db_path}?mode=ro', uri=True, timeout=10)
        rows = con.execute('SELECT status, COUNT(*) FROM jobs GROUP BY status').fetchall()
        con.close()
        return dict(rows)
    except Exception:
        return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True, help='Path to shard SQLite database (e.g. shard_1.sqlite)')
    parser.add_argument('--workers', type=int, default=max(1, min(os.cpu_count() or 4, 8)),
                        help='Number of parallel workers (default: min(cores, 8))')
    parser.add_argument('--bundle', type=Path,
                        default=Path('/data1/pl/ImageTask/wxq/Projects/standalone-rollout-readiness-20260929/candidate-release-v5'),
                        help='Path to candidate-release-v5 bundle directory')
    parser.add_argument('--game-dir', type=Path, default=None,
                        help='Override path to game assets folder containing SlayTheSpire2.pck')
    parser.add_argument('--dotnet', type=Path, default=None,
                        help='Override path to dotnet executable')
    parser.add_argument('--work-dir', type=Path, default=None,
                        help='Directory for worker runtime configs, scratch files and logs')
    parser.add_argument('--limit', type=int, default=1000000,
                        help='Max battles to process per worker in this run (default: run until complete)')
    args = parser.parse_args()

    db_path = args.db.resolve()
    if not db_path.exists():
        sys.exit(f'Error: shard database not found: {db_path}')

    work_dir = args.work_dir
    if work_dir is None:
        work_dir = db_path.parent / f'{db_path.stem}_work'
    work_dir = work_dir.resolve()

    bundle_path = args.bundle
    if not bundle_path.exists():
        # Fall back to configs/simulator.json if present
        cfg_sim = ROOT / 'configs/simulator.json'
        if cfg_sim.exists():
            try:
                bundle_path = Path(json.loads(cfg_sim.read_text())['bundle'])
            except Exception:
                pass
    if not bundle_path.exists():
        sys.exit(f'Error: simulator bundle not found at {bundle_path}. Specify with --bundle')

    print('=' * 65)
    print(f'Starting Shard Runner')
    print(f'  Database  : {db_path}')
    print(f'  Workers   : {args.workers}')
    print(f'  Bundle    : {bundle_path}')
    print(f'  Work Dir  : {work_dir}')
    print('=' * 65)

    initial_counts = query_db_counts(db_path)
    total_jobs = sum(initial_counts.values())
    pending_jobs = initial_counts.get('pending', 0)
    completed_jobs = initial_counts.get('complete', 0)
    print(f'Initial status: {completed_jobs:,} complete / {pending_jobs:,} pending / {total_jobs:,} total')

    if pending_jobs == 0 and total_jobs > 0:
        print('All jobs in this shard are already complete!')
        return

    bundle_info = load_bundle(bundle_path)
    runtimes = prepare_runtimes(
        work_dir,
        bundle_info,
        args.workers,
        game_dir=str(args.game_dir) if args.game_dir else None,
        dotnet=str(args.dotnet) if args.dotnet else None,
    )

    env = dict(os.environ)
    env['PYTHONPATH'] = str(ROOT) + (os.pathsep + env['PYTHONPATH'] if 'PYTHONPATH' in env else '')

    cmd = [
        sys.executable, '-u', '-m', 'tools.collect_parallel',
        '--db', str(db_path),
        '--config', bundle_info['config'],
        '--teacher', bundle_info['teacher'],
        '--catalog', bundle_info['catalog'],
        '--runtimes', *runtimes,
        '--limit-per-worker', str(args.limit),
        '--continuous-workers',
        '--reserve-gib', '0',
        '--worker-start-gib', '2',
    ]

    print(f'Launching parallel collector with {args.workers} workers...')
    proc = subprocess.Popen(cmd, env=env, cwd=ROOT)

    def signal_handler(signum, frame):
        print('\n[Shard Runner] Stop signal received. Gracefully draining workers...')
        for r_path in runtimes:
            try:
                r_info = json.loads(Path(r_path).read_text())
                stop_marker = Path(r_info['data_dir']) / 'collector.stop'
                stop_marker.touch()
            except Exception:
                pass

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    start_time = time.time()
    last_completed = completed_jobs

    try:
        while proc.poll() is None:
            time.sleep(15)
            counts = query_db_counts(db_path)
            c = counts.get('complete', 0)
            p = counts.get('pending', 0)
            f = counts.get('failed', 0)
            tot = sum(counts.values()) or total_jobs
            elapsed = time.time() - start_time
            delta = c - last_completed
            rate = delta / max(1.0, elapsed)
            eta_h = (p / max(1e-3, rate)) / 3600 if rate > 0 else 0.0

            pct = (c / max(1, tot)) * 100.0
            print(
                f'[{time.strftime("%H:%M:%S")}] Completed: {c:,}/{tot:,} ({pct:.1f}%) | '
                f'Pending: {p:,} | Failed: {f} | Speed: {rate:.2f} battles/s | ETA: {eta_h:.1f}h',
                flush=True,
            )
            if p == 0:
                print('\nAll pending jobs finished!')
                break
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()

    final_counts = query_db_counts(db_path)
    print('\n' + '=' * 65)
    print('Shard Execution Summary:')
    for k, v in sorted(final_counts.items()):
        print(f'  {k:12s}: {v:,}')
    print('=' * 65)


if __name__ == '__main__':
    main()
