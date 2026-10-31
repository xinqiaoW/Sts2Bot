"""Prepare every configured 8s source, train models, and produce a report.

Run from the training environment. Each stage has a durable process/state/log
record, and a failed source prevents partial-corpus training. Re-running reuses
completed source caches; use a new directory for a fresh live-data snapshot.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time

import psutil

ROOT = Path(__file__).resolve().parents[1]


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix+'.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2)+'\n')
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--config', type=Path, default=ROOT/'train/configs/sources-full-8s.json')
    parser.add_argument('--gpus', default='6,7')
    parser.add_argument('--models', nargs='+', default=['repo_mlp', 'tabm', 'lightgbm'])
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    directory = args.directory.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    with (directory/'pipeline.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        config = json.loads(args.config.read_text())
        atomic_json(directory/'sources.json', config)
        snapshot = directory/'snapshot'
        cache = snapshot/'sources'
        cache.mkdir(parents=True, exist_ok=True)
        logs = directory/'logs'
        logs.mkdir(exist_ok=True)
        state = {'pid': os.getpid(), 'created': psutil.Process().create_time(),
                 'started_at': datetime.now(timezone.utc).isoformat(), 'directory': str(directory),
                 'config': str(args.config.resolve()), 'models': args.models, 'gpus': args.gpus,
                 'code_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in list((ROOT/'train').glob('*.py')) + [Path(__file__)]},
                 'completed_stages': []}

        def save(**extra):
            state.update(extra)
            state['updated_at'] = datetime.now(timezone.utc).isoformat()
            atomic_json(directory/'pipeline-state.json', state)

        def run(stage, command):
            log_path = logs/(stage+'.log')
            with log_path.open('ab', buffering=0) as log:
                child = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL,
                                         stdout=log, stderr=subprocess.STDOUT)
                save(state='running', stage=stage, child_pid=child.pid,
                     child_created=psutil.Process(child.pid).create_time(), command=command, log=str(log_path))
                print(json.dumps({'event': 'stage_started', 'stage': stage, 'pid': child.pid,
                                  'log': str(log_path)}), flush=True)
                code = child.wait()
            if code:
                save(state='failed', exit_code=code)
                raise RuntimeError(f'{stage} failed (exit {code}); inspect {log_path}')
            state['completed_stages'].append(stage)
            save(child_pid=None, child_created=None)

        # Scan the damaged frozen batch first; export live sources last so they
        # are fresh when preparation completes. Merge priority stays in config.
        pending = []
        suffixes = ['.battles.parquet', '.builds.json.gz', '.edges.json.gz', '.meta.json']
        for source in config['sources']:
            name = source['name']
            if all((cache/(name+s)).is_file() for s in suffixes):
                meta = json.loads((cache/(name+'.meta.json')).read_text())
                if meta['name'] != name or meta['kind'] != source['kind'] or meta.get('verify_cards') is not True:
                    raise ValueError('Unverified or mismatched source cache: '+name)
                if any(t.get('search_ms') != 8000 for t in meta['teachers'].values()):
                    raise ValueError('Non-8s source cache: '+name)
                continue
            pending.append(source)
        def order(source):
            return (0 if source.get('recover_invalid_rows') else 2 if not source.get('frozen') else 1,
                    config['sources'].index(source))
        try:
            save(state='starting', pending_sources=[s['name'] for s in pending])
            for source in sorted(pending, key=order):
                run('export-'+source['name'], [sys.executable, '-P', '-u', '-m', 'train.stream_export',
                    '--config', str(directory/'sources.json'), '--output', str(cache), '--only', source['name']])
            run('merge', [sys.executable, '-P', '-u', '-m', 'train.snapshot', '--config',
                         str(directory/'sources.json'), '--output', str(snapshot), '--merge-only',
                         '--allow-backend-mixture'])
            run('features', [sys.executable, '-P', '-u', '-c',
                'from train.data import Dataset,load_catalog; import json; '
                f'd=Dataset.load({str(snapshot)!r},load_catalog()); print(json.dumps(d.summary()),flush=True)'])
            if args.prepare_only:
                save(state='prepared', stage='prepared')
                return
            allowed = {int(g) for g in args.gpus.split(',') if g.strip()}
            if not allowed:
                raise ValueError('At least one permitted GPU is required')
            while True:
                result = subprocess.run(['nvidia-smi', '--query-gpu=index,memory.used,utilization.gpu',
                                         '--format=csv,noheader,nounits'], check=True, capture_output=True, text=True)
                free = []
                for line in result.stdout.splitlines():
                    gpu, memory, utilization = [int(v.strip()) for v in line.split(',')]
                    if gpu in allowed and memory < 512 and utilization < 5:
                        free.append(gpu)
                if free:
                    break
                save(state='waiting', stage='waiting-for-gpu', allowed_gpus=sorted(allowed))
                time.sleep(30)
            selected_gpus = ','.join(str(g) for g in free)
            save(selected_gpus=selected_gpus)
            run('train', [sys.executable, '-P', '-u', '-m', 'train.compare', '--snapshot', str(snapshot),
                         '--models', *args.models, '--gpus', selected_gpus,
                         '--output', str(directory/'checkpoints'), '--report-dir', str(directory/'report'),
                         '--set', 'num_threads=8', 'batch_size=1024'])
            # compare records individual failures instead of raising; require
            # every requested model to have real artifacts and finite metrics.
            report = json.loads((directory/'report/comparison.json').read_text())
            successful = {m['model'] for m in report['models'] if m['status'] == 'ok'}
            if successful != set(args.models):
                raise RuntimeError('Some models did not finish: '+str(set(args.models)-successful))
            for model in report['models']:
                for split in ['validation', 'test']:
                    for metric in ['pair_mae_hp', 'pair_rmse_hp', 'row_mae_hp', 'row_rmse_hp', 'death_brier']:
                        if not math.isfinite(model[split][metric]):
                            raise RuntimeError(f"Non-finite {split}/{metric} for {model['model']}")
            primary = 'tabm' if 'tabm' in args.models else args.models[0]
            run('inspect', [sys.executable, '-P', '-u', '-m', 'train.inspect', '--snapshot', str(snapshot),
                            '--checkpoints', str(directory/'checkpoints'), '--primary', primary,
                            '--output', str(directory/'report/examples-test.md')])
            save(state='complete', stage='complete', finished_at=datetime.now(timezone.utc).isoformat())
        except BaseException as exc:
            save(state='failed', error=f'{type(exc).__name__}: {exc}')
            raise


if __name__ == '__main__':
    main()
