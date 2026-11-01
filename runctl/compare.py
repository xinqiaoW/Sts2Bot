"""Compare complete, paired native experiments; never score failed runs as losses."""
import argparse
import json
from pathlib import Path

from .env import atomic_json


def compare_experiments(directories):
    rows, by_seed = [], {}
    for name, directory in directories.items():
        directory = Path(directory)
        summary = json.loads((directory/'summary.json').read_text())
        manifest = json.loads((directory/'experiment.json').read_text())
        if summary['completed'] != summary['requested'] or summary['failed_workers']:
            raise ValueError(f'{name}: experiment has incomplete or failed attempts')
        episodes = [e for w in summary['workers'] for e in w['episodes']]
        seeds = [e['seed'] for e in episodes]
        if len(set(seeds)) != len(episodes): raise ValueError(f'{name}: repeated seed within experiment')
        if len({e['runId'] for e in episodes}) != len(episodes): raise ValueError(f'{name}: repeated run ID')
        by_seed[name] = dict(zip(seeds, episodes))
        row = {k: summary[k] for k in ('completed', 'wins', 'deaths', 'win_rate', 'win_rate_wilson95', 'mean_floor', 'mean_act')}
        row.update(name=name, directory=str(directory), source_revision=manifest['source_revision'])
        row.update(failed_attempts=summary.get('failed_attempts', 0), retries=summary.get('retries', []))
        rows.append(row)
    if not rows: raise ValueError('No experiments supplied')
    seed_sets = [set(episodes) for episodes in by_seed.values()]
    if any(seeds != seed_sets[0] for seeds in seed_sets[1:]): raise ValueError('Tuning experiments must use the same seeds')
    revisions = {r['source_revision'] for r in rows}
    if len(revisions) != 1 or 'unrecorded' in revisions: raise ValueError('Require one recorded source revision')
    ranked = sorted(rows, key=lambda r: (-r['wins'], -r['mean_floor'], r['name']))
    selected = ranked[0]['name']
    pairs = []
    for other in by_seed:
        if other == selected: continue
        a = by_seed[selected]; b = by_seed[other]
        pairs.append(dict(selected=selected, other=other,
            selected_only_wins=sum(a[s]['outcome']=='victory' and b[s]['outcome']=='death' for s in a),
            other_only_wins=sum(a[s]['outcome']=='death' and b[s]['outcome']=='victory' for s in a)))
    return dict(selection_rule='most wins; then greatest mean terminal floor; then name',
                selected=selected, experiments=rows, paired_comparisons=pairs,
                tuning_games=sum(r['completed'] for r in rows), independent_seed_count=len(seed_sets[0]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', action='append', required=True, metavar='NAME=PATH')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    directories = {}
    for item in args.experiment:
        name, path = item.split('=', 1)
        if name in directories: parser.error('Experiment names must be unique')
        directories[name] = path
    result = compare_experiments(directories)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
