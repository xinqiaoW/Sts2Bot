"""Run a fixed experiment across explicitly isolated native workers.

Failures remain failures; neither replacement seeds nor synthetic losses are
inserted to reach the requested number of completed games.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import math
from pathlib import Path
import subprocess
import sys
import time

from .env import atomic_json


def summarize(workers, requested):
    episodes = [episode for worker in workers for episode in worker.get('episodes', [])]
    count = len(episodes)
    wins = sum(e['outcome'] == 'victory' for e in episodes)
    rate = wins/count if count else None
    interval = None
    if count:
        z = 1.96
        center = (rate+z*z/(2*count))/(1+z*z/count)
        radius = z*math.sqrt(rate*(1-rate)/count+z*z/(4*count*count))/(1+z*z/count)
        interval = [max(0, center-radius), min(1, center+radius)]
    return dict(requested=requested, completed=count, wins=wins, deaths=count-wins,
        win_rate=rate, win_rate_wilson95=interval,
        mean_floor=sum(e['state']['floor'] for e in episodes)/count if count else None,
        mean_act=sum(e['state']['act'] for e in episodes)/count if count else None,
        failed_workers=sum(w['returncode'] != 0 for w in workers), workers=workers)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--runtime-dir', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--episodes', type=int, required=True)
    parser.add_argument('--seed-prefix', required=True)
    parser.add_argument('--policy-config', type=Path)
    parser.add_argument('--timeout', type=int, default=3600)
    args = parser.parse_args()
    runtimes = sorted(args.runtime_dir.glob('worker-*/runtime.json'))
    if not runtimes or args.episodes < 1: parser.error('Require prepared runtimes and positive episodes')
    args.output.mkdir(parents=True, exist_ok=False)
    configs = [json.loads(p.read_text()) for p in runtimes]
    if len({Path(c['data_dir']).resolve() for c in configs}) != len(configs):
        raise ValueError('Workers must have separate native data directories')
    counts = [args.episodes//len(runtimes) + (i < args.episodes % len(runtimes)) for i in range(len(runtimes))]
    atomic_json(args.output/'experiment.json', dict(started=time.time(), episodes=args.episodes,
        seed_prefix=args.seed_prefix, runtimes=[str(p.resolve()) for p in runtimes],
        per_worker=counts, policy_config=str(args.policy_config.resolve()) if args.policy_config else None))

    def worker(index, count):
        output = args.output/f'worker-{index:02d}'
        command = [sys.executable, '-m', 'runctl', '--runtime', str(runtimes[index]),
            '--episodes', str(count), '--seed-prefix', f'{args.seed_prefix}W{index:02d}R',
            '--output', str(output), '--timeout', str(args.timeout)]
        if args.policy_config: command += ['--policy-config', str(args.policy_config)]
        with (args.output/f'worker-{index:02d}.log').open('w') as log:
            completed = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT)
        result = dict(index=index, requested=count, returncode=completed.returncode, episodes=[])
        summary, failure = output/'summary.json', output/'failure.json'
        if summary.exists(): result['episodes'] = json.loads(summary.read_text())['episodes']
        if failure.exists(): result['failure'] = json.loads(failure.read_text())
        return result

    results = []
    with ThreadPoolExecutor(max_workers=len(runtimes)) as pool:
        futures = [pool.submit(worker, i, count) for i, count in enumerate(counts) if count]
        for future in as_completed(futures):
            results.append(future.result())
            results.sort(key=lambda r: r['index'])
            summary = summarize(results, args.episodes)
            atomic_json(args.output/'summary.json', summary)
            print(json.dumps({k: summary[k] for k in ('requested', 'completed', 'wins', 'deaths', 'failed_workers', 'mean_floor')}), flush=True)
    if summary['completed'] != args.episodes or summary['failed_workers']:
        raise SystemExit(1)


if __name__ == '__main__': main()
