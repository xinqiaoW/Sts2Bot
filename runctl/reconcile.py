"""Explicitly resolve failed experiment slots with recorded same-seed retries.

Original experiments and failed artifacts are immutable. This produces a new
summary with links to both attempts, never a synthetic outcome.
"""
import argparse
from copy import deepcopy
import json
from pathlib import Path

from .batch import summarize
from .env import atomic_json


def reconcile(source, retries):
    source = Path(source).resolve()
    original = json.loads((source / 'summary.json').read_text())
    manifest = json.loads((source / 'experiment.json').read_text())
    workers = deepcopy(original['workers'])
    if sum(w['requested'] for w in workers) != original['requested']:
        raise ValueError('Original batch is still running or missing workers')
    records = []
    for index, retry in retries.items():
        retry = Path(retry).resolve()
        matches = [w for w in workers if w['index'] == index]
        if len(matches) != 1:
            raise ValueError('Unknown worker index')
        worker = matches[0]
        if worker['returncode'] == 0 or worker['episodes'] or worker['requested'] != 1:
            raise ValueError('Retry requires a failed single-episode worker without a terminal result')
        failure = worker['failure']
        result = json.loads((retry / 'summary.json').read_text())
        episodes = result['episodes']
        if (retry / 'failure.json').exists() or result['completed'] != 1 or len(episodes) != 1:
            raise ValueError('Retry has not completed successfully')
        episode = episodes[0]
        if episode['seed'] != failure['seed'] or episode['runId'] == failure['runId']:
            raise ValueError('Retry must use the same seed and a new run ID')
        if episode['status'] != 'complete' or episode['outcome'] not in ('death', 'victory'):
            raise ValueError('Retry has no natural terminal outcome')
        old_config = json.loads((source / f'worker-{index:02d}' / 'policy-config.json').read_text())
        new_config = json.loads((retry / 'policy-config.json').read_text())
        provenance = json.loads((retry / 'retry-provenance.json').read_text())
        if (new_config != old_config or provenance['source_revision'] != manifest['source_revision']
                or provenance['failed_run_id'] != failure['runId']):
            raise ValueError('Retry configuration or source provenance differs')
        records.append(dict(index=index, original_failure=failure, retry_directory=str(retry),
                            completed_run_id=episode['runId'], provenance=provenance))
        worker.update(returncode=0, episodes=episodes, resolved_failure=worker.pop('failure'))
    result = summarize(workers, original['requested'])
    if result['failed_workers'] or result['completed'] != result['requested']:
        raise ValueError('Unresolved failed or incomplete slots remain')
    result.update(original_experiment=str(source), failed_attempts=original['failed_workers'], retries=records)
    manifest.update(original_experiment=str(source), retries=records)
    return result, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--retry', action='append', required=True, metavar='INDEX=PATH')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    retries = {}
    for item in args.retry:
        index, path = item.split('=', 1)
        index = int(index)
        if index in retries: parser.error('Duplicate retry index')
        retries[index] = path
    summary, manifest = reconcile(args.source, retries)
    args.output.mkdir(parents=True, exist_ok=False)
    atomic_json(args.output / 'summary.json', summary)
    atomic_json(args.output / 'experiment.json', manifest)
    print(json.dumps({k: summary[k] for k in ('completed', 'wins', 'deaths', 'failed_attempts')}))


if __name__ == '__main__':
    main()
