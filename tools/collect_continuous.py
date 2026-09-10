"""Adopt a pool and replenish it with verified real precombat inventories.

Linux process locks prevent duplicate controllers and concurrent queue expansion.
Stopping this controller leaves an already running pool to finish its current work.
"""
import argparse
from contextlib import contextmanager
import fcntl
import json
import math
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

from damage_model.catalog import Catalog
from damage_model.provenance import teacher_for
from damage_model.schema import canonical
from damage_model.store import Store
from tools.collect_parallel import available_gib, deadline_reached, validate_memory_bounds, validate_runtimes


MEMORY_PAUSES = {
    'Insufficient available memory to add a worker',
    'Available memory fell below reserve; draining workers',
}


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False), encoding='utf-8')
    temporary.replace(path)


@contextmanager
def exclusive(path):
    with Path(path).open('a+') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
        else:
            try:
                yield True
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)


def read_json(path, default=None):
    return json.loads(Path(path).read_text(encoding='utf-8')) if Path(path).exists() else default


def next_action(counts, parallel_state, parallel_error=None):
    if not counts:
        return 'wait'
    memory_pause = parallel_state == 'failed' and parallel_error in MEMORY_PAUSES
    if counts.get('failed', 0) or (parallel_state in ('failed', 'draining') and not memory_pause):
        raise ValueError('Collector failure requires diagnosis before continuing')
    if counts.get('running', 0):
        raise ValueError('Running leases remain without an active pool; diagnose orphaned workers')
    if parallel_state in ('starting', 'collecting', 'training'):
        raise ValueError('Pool lock was released without a clean terminal state')
    return 'collect' if counts.get('pending', 0) else 'validate'


def checkpoint_directory(total, initial_samples, initial_output, output_root):
    if total < initial_samples:
        raise ValueError('Dataset is smaller than the initial panel')
    return Path(initial_output) if total == initial_samples else Path(output_root) / f'samples-{total:09d}'


class Controller:
    def __init__(self, args):
        self.args = args
        self.db_path = Path(args.db)
        self.store = Store(args.db)
        self.configs = validate_runtimes(args.runtimes)
        self.status_path = self.db_path.with_suffix('.continuous.json')
        self.progress_path = self.db_path.with_suffix('.continuous.progress.json')
        self.stop_path = self.db_path.with_suffix('.continuous.stop')
        self.progress = read_json(self.progress_path, {'validated': [], 'initial_samples': args.initial_samples})
        if self.progress['initial_samples'] != args.initial_samples:
            raise ValueError('Initial panel size changed across controller restart')
        self.stop_requested = False
        self.child = None
        self.command = [sys.executable, '-u', '-m', 'damage_model.cli', '--db', args.db, '--config', args.config]
        self.catalog = Catalog.load('catalogs/game-0.111.0.raw.json', args.config)
        from damage_model.target_scope import require_policy
        require_policy(self.store, self.catalog.config)
        teacher = canonical(teacher_for(self.catalog, 'configs/teacher.json'))
        if {r[0] for r in self.store.db.execute('SELECT DISTINCT teacher FROM jobs')} - {teacher}:
            raise ValueError('Active dataset must use the current frozen teacher')
        self.mutation_store = None
        self.generator = None
        if getattr(args, 'mutation_db', None):
            if not args.collect_only:
                raise ValueError('Mutation collection requires collect-only mode')
            from damage_model.mutations import Generator
            from damage_model.priority_store import PriorityStore
            self.mutation_store = Store(args.mutation_db)
            self.generator = Generator(self.store, self.mutation_store, self.catalog,
                                       json.loads(teacher), read_json(args.mutation_policy))
            self.queues = PriorityStore(self.store, self.mutation_store, json.loads(teacher))

    def work_counts(self):
        return self.queues.counts() if getattr(self, 'mutation_store', None) is not None else self.store.counts()

    def status(self, state, **details):
        atomic_json(self.status_path, {'state': state, 'updated': time.time(), 'pid': os.getpid(),
            'db': str(self.db_path), 'counts': self.store.counts(),
            'mutation_db': getattr(self.args, 'mutation_db', None),
            'mutation_counts': self.mutation_store.counts() if getattr(self, 'mutation_store', None) is not None else {},
            'initial_samples': self.args.initial_samples, 'validated_rounds': len(self.progress['validated']),
            'configured_workers': len(self.args.runtimes), 'reserve_gib': self.args.reserve_gib,
            'worker_start_gib': self.args.worker_start_gib,
            'collect_only': self.args.collect_only, 'stop_at': self.args.stop_at,
            'last_validated': self.progress['validated'][-1] if self.progress['validated'] else None,
            **details})

    def guard(self):
        active = read_json(self.args.active_pointer)
        if not active or Path(active['active_db']).resolve() != self.db_path.resolve():
            raise ValueError('Active database pointer changed; controller must not collect the old teacher')
        if getattr(self.args, 'mutation_db', None) and active.get('mutation_db') != self.args.mutation_db:
            raise ValueError('Active mutation database pointer changed')
        if shutil.disk_usage(self.db_path.parent).free < 20 * 1024**3:
            raise RuntimeError('Less than 20 GiB free disk; preserve data and diagnose')

    def validate_or_train(self, total):
        if self.args.collect_only:
            rounds = self.progress.setdefault('collected', [])
            if not any(r['completed_samples'] == total for r in rounds):
                rounds.append({'completed_samples': total, 'collected_at': time.time(),
                               'training_deferred': True})
                atomic_json(self.progress_path, self.progress)
            self.status('panel_collected', completed_samples=total, training_deferred=True)
            return
        from damage_model.checkpoint_validation import validate_checkpoint
        output = checkpoint_directory(total, self.args.initial_samples, self.args.initial_output, self.args.output_root)
        model, metrics = output / 'model.pt', output / 'metrics.json'
        if model.exists() != metrics.exists():
            raise ValueError(f'Incomplete checkpoint at {output}; preserve it for diagnosis')
        if not model.exists():
            if available_gib() < self.args.reserve_gib + 2:
                raise RuntimeError('Insufficient memory to train with the required reserve')
            self.status('training', output=str(output))
            subprocess.run(self.command + ['train', '--device', 'cpu', '--output', str(output)], check=True)
        self.status('validating', output=str(output))
        report = validate_checkpoint(self.store, self.catalog, output)
        atomic_json(output / 'validation.json', report)
        entry = {'completed_samples': total, 'checkpoint': str(model),
                 'validation': str(output / 'validation.json'), 'model_sha256': report['model_sha256'],
                 'job_ids_sha256': report['job_ids_sha256'], 'validated_at': time.time()}
        previous = [r for r in self.progress['validated'] if r['completed_samples'] == total]
        if previous:
            if any(previous[0][k] != entry[k] for k in ('checkpoint', 'model_sha256', 'job_ids_sha256')):
                raise ValueError('Previously validated checkpoint or dataset was changed')
        else:
            self.progress['validated'].append(entry)
            atomic_json(self.progress_path, self.progress)
        print(json.dumps({'event': 'checkpoint_validated', **entry, 'metrics': report['metrics'],
                          'baselines': report['baselines']}), flush=True)

    def refill(self):
        counts = self.store.counts()
        if counts.get('failed', 0) or counts.get('pending', 0) >= self.args.queue_high_water:
            return
        teacher = teacher_for(self.catalog, 'configs/teacher.json')
        if getattr(self.args, 'backfill_dir', None):
            from damage_model.source_backfill import sync_sources
            report = sync_sources(self.store,self.catalog,teacher,self.args.source_dir,
                                  self.args.source_start,self.args.backfill_dir)
        else:
            from damage_model.run_source import sync_page
            report = sync_page(self.store,self.catalog,teacher,self.args.source_dir,self.args.source_start)
        if report['state'] != 'waiting_source' or report.get('error'):
            print(json.dumps({'event':'source_sync', **report}), flush=True)

    def refill_mutations(self):
        if getattr(self, 'generator', None) is None: return
        if self.store.counts().get('pending', 0) or self.work_counts().get('failed', 0): return
        policy = self.generator.policy
        counts = self.mutation_store.counts()
        if counts.get('pending', 0) < policy['queue_low_water']:
            report = self.generator.refill()
            print(json.dumps({'event': 'mutation_refill', **report}), flush=True)

    def memory_ready(self, for_pool):
        required = self.args.reserve_gib + (self.args.worker_start_gib * len(self.args.runtimes) if for_pool else 2)
        available = available_gib()
        if available < required:
            self.status('waiting_memory', available_gib=available, required_gib=required,
                        note='No new game processes; resume automatically when the memory reserve permits')
            return False
        return True

    def run(self):
        Path('logs').mkdir(exist_ok=True)
        while True:
            if deadline_reached(self.args.stop_at):
                for config in self.configs:
                    (Path(config['data_dir']) / 'collector.stop').touch()
                self.status('paused', note='Requested deadline reached; current battles drain')
                return
            if self.stop_requested or self.stop_path.exists():
                self.status('paused', note='An existing pool can finish; no new pool will be launched')
                return
            self.guard()
            self.refill()
            self.refill_mutations()
            if self.child is not None and self.child.poll() is not None:
                child_pid = self.child.pid
                code = self.child.wait()
                self.child = None
                if code:
                    previous = read_json(self.db_path.with_suffix('.parallel.json'), {})
                    if (previous.get('pid') != child_pid or previous.get('state') != 'failed'
                            or previous.get('error') not in MEMORY_PAUSES):
                        raise RuntimeError(f'Owned collector pool exited with code {code}')
            launch = False
            # Hold the pool lock through training/expansion, so manual pools cannot race this transition.
            with exclusive(self.db_path.with_suffix('.pool.lock')) as acquired:
                if not acquired:
                    parallel = read_json(self.db_path.with_suffix('.parallel.json'), {})
                    self.status('following_pool', pool=parallel)
                elif self.child is not None:
                    # Popen may return before its new supervisor has acquired the pool lock.
                    self.status('starting_pool', child_pid=self.child.pid)
                else:
                    for config in self.configs:
                        with exclusive(Path(config['data_dir']) / 'collector.lock') as worker_free:
                            if not worker_free:
                                raise RuntimeError('Collector worker still holds its lock without a pool')
                    counts = self.work_counts()
                    parallel = read_json(self.db_path.with_suffix('.parallel.json'), {})
                    action = next_action(counts, parallel.get('state'), parallel.get('error'))
                    if action == 'wait':
                        self.status('waiting_source')
                    elif self.memory_ready(for_pool=action == 'collect'):
                        if action == 'validate':
                            total = counts['complete']
                            self.validate_or_train(total)
                            if self.stop_requested or self.stop_path.exists() or deadline_reached(self.args.stop_at):
                                continue
                            self.status('waiting_source', completed_samples=total)
                        launch = action == 'collect'
            if launch:
                if self.stop_requested or self.stop_path.exists() or deadline_reached(self.args.stop_at):
                    continue
                if self.memory_ready(for_pool=True):
                    with Path('logs/continuous-pool.log').open('ab') as stream:
                        self.child = subprocess.Popen([sys.executable, '-u', '-m', 'tools.collect_parallel',
                            '--db', str(self.db_path), '--config', getattr(self.args, 'config', 'configs/real-runs.json'),
                            '--runtimes', *self.args.runtimes,
                            '--reserve-gib', str(self.args.reserve_gib),
                            '--worker-start-gib', str(self.args.worker_start_gib), '--limit-per-worker', '6080',
                            *(['--fallback-db', self.args.mutation_db] if getattr(self.args, 'mutation_db', None) else []),
                            *(['--stop-at', str(self.args.stop_at)] if self.args.stop_at is not None else [])],
                            stdout=stream, stderr=subprocess.STDOUT, start_new_session=True)
                    self.status('starting_pool', child_pid=self.child.pid)
            for _ in range(self.args.poll_seconds):
                if self.stop_requested or self.stop_path.exists():
                    break
                time.sleep(1)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', default='data/collection-real-runs-v2.sqlite')
    p.add_argument('--config', default='configs/real-runs.json')
    p.add_argument('--mutation-db', help='Separate one-generation mutation queue used when real tasks run out')
    p.add_argument('--mutation-policy', default='configs/mutations-8s.json')
    p.add_argument('--source-dir', default='data/external/spire-codex')
    p.add_argument('--source-start', default='2026-09-05T00:00:00Z')
    p.add_argument('--backfill-dir', help='Separate durable historical cursors sharing the live export rate limit')
    p.add_argument('--queue-high-water', type=int, default=12000)
    p.add_argument('--active-pointer', default='data/active-collection.json')
    p.add_argument('--runtimes', nargs='+', required=True)
    p.add_argument('--reserve-gib', type=float, default=32)
    p.add_argument('--worker-start-gib', type=float, default=3)
    p.add_argument('--initial-samples', type=int, default=6080)
    p.add_argument('--initial-output', default='checkpoints/v1')
    p.add_argument('--output-root', default='checkpoints/continuous')
    p.add_argument('--poll-seconds', type=int, default=15)
    p.add_argument('--collect-only', action='store_true', help='Defer model training; continue importing real runs')
    p.add_argument('--stop-at', type=float, help='UTC Unix deadline shared with each pool')
    args = p.parse_args()
    validate_memory_bounds(args.reserve_gib, args.worker_start_gib)
    if args.stop_at is not None and (not math.isfinite(args.stop_at) or args.stop_at <= 0):
        raise ValueError('Invalid collection deadline')
    if not 1 <= args.poll_seconds <= 60 or args.initial_samples < 1:
        raise ValueError('Invalid continuous collection bounds')
    if not Path(args.db).is_file():
        raise ValueError('Existing imported database required')
    with exclusive(Path(args.db).with_suffix('.continuous.lock')) as acquired:
        if not acquired:
            raise RuntimeError('A continuous controller already holds this dataset')
        controller = Controller(args)
        def stop(signum, frame):
            controller.stop_requested = True
        for sig in (signal.SIGINT, signal.SIGTERM):
            signal.signal(sig, stop)
        try:
            controller.run()
        except BaseException as error:
            controller.status('failed', error=str(error))
            raise
        finally:
            controller.store.db.close()
            if controller.mutation_store is not None: controller.mutation_store.db.close()


if __name__ == '__main__':
    main()
