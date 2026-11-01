"""Audit completed native games against their actual decision/action records."""
import argparse
from collections import Counter
import json
from pathlib import Path

from .env import atomic_json


def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def audit_episode(episode, policy_directory):
    native = Path(episode['artifactDirectory'])
    accepted, result = read(native / 'accepted.json'), read(native / 'result.json')
    expected = {k: v for k, v in episode.items() if k not in ('seed', 'artifactDirectory')}
    if result != expected: raise ValueError('Summary differs from native terminal result')
    if accepted['seed'] != episode['seed'] or accepted['runId'] != episode['runId']:
        raise ValueError('Accepted request identity differs')
    if (accepted['characterId'], accepted['ascension'], accepted['combatMode'], accepted['decisionMode']) != ('SILENT', 10, 'solver', 'all'):
        raise ValueError('Unexpected game or control mode')
    if result['status'] != 'complete' or result['outcome'] not in ('death', 'victory'):
        raise ValueError('No natural terminal outcome')
    if result['outcome'] == 'death' and result['state']['hp'] != 0:
        raise ValueError('Death result with nonzero HP')
    decisions, actions, start = {}, {}, None
    for line in (native / 'events.jsonl').open(encoding='utf-8'):
        event = json.loads(line)
        if event['runId'] != episode['runId']: raise ValueError('Foreign native event')
        value = event['payload']
        if event['kind'] == 'run_started': start = value
        if event['kind'] == 'decision':
            seq = value['decisionSeq']
            if seq in decisions: raise ValueError('Duplicate native decision')
            decisions[seq] = value
        if event['kind'] == 'action':
            action = value['details']; seq = action['decisionSeq']
            if seq in actions: raise ValueError('Duplicate native action')
            actions[seq] = action
    if start is None or (start['state']['hp'], start['state']['maxHp']) != (56, 70) or not start['details']['fullContentDiscovery']:
        raise ValueError('Unexpected initial game state')
    rows = [json.loads(line) for line in (Path(policy_directory) / 'decisions.jsonl').open(encoding='utf-8')]
    rows = [r for r in rows if r['runId'] == episode['runId']]
    config = read(Path(policy_directory) / 'policy-config.json')
    sequence = set(range(1, result['decisionCount'] + 1))
    if set(decisions) != sequence or set(actions) != sequence or {r['decisionSeq'] for r in rows} != sequence or len(rows) != len(sequence):
        raise ValueError('Missing, duplicate or unexecuted policy/native decisions')
    screens, events, warnings = Counter(), Counter(), Counter()
    timings, crisis_timings = [], []
    threshold_choices = expansions = 0
    for row in rows:
        seq, choice = row['decisionSeq'], row['choice']
        observation = decisions[seq]
        if row['config'] != config or row['seed'] != episode['seed']:
            raise ValueError('Decision configuration or seed changed')
        if actions[seq]['choice'] != choice or observation['screen'] != row['screen']:
            raise ValueError('Executed action differs from policy log')
        option = observation['options'][choice]
        screens[row['screen']] += 1
        if row['screen'] == 'EVENT': events[observation['context']['eventId']] += 1
        warnings.update(row['warnings'])
        timings.append(row['elapsed_seconds'])
        search = row.get('card_search', row)
        if 'rollout_depth' in search:
            if search['crisis']:
                crisis_timings.append(row['elapsed_seconds'])
                if search['rollout_depth'] > 0: expansions += 1
            width = search['keep_per_parent']
            for depth in search['stats']['per_depth']:
                if any(count != width ** depth['depth'] for count in depth['leaves_per_root']):
                    raise ValueError('Rollout did not preserve every parent branch')
            skip = next((o for o in observation['options'] if o['kind'] in ('skip', 'leave') or
                         o['kind'] == 'alternative' and o.get('id', '').upper() == 'SKIP'), None)
            if skip is not None and option['kind'] == 'card' and option.get('action', 'take') == 'take':
                margin = config['crisis_card_min_gain'] if search['crisis'] else config['normal_card_min_gain']
                if search['scores'][str(choice)] <= search['skip_score'] + margin:
                    raise ValueError(f'Selected card violates strict skip margin: {episode["runId"]}:{seq}')
                threshold_choices += 1
    return dict(run_id=episode['runId'], seed=episode['seed'], outcome=episode['outcome'],
                screens=dict(screens), events=dict(events), warnings=dict(warnings),
                checked_decisions=len(rows), threshold_card_takes=threshold_choices,
                crisis_expansions=expansions, decision_seconds=timings, crisis_seconds=crisis_timings)


def audit_experiment(directory):
    directory = Path(directory)
    summary = read(directory / 'summary.json')
    if summary['completed'] != summary['requested'] or summary['failed_workers']:
        raise ValueError('Require complete experiment, with every failure explicitly resolved')
    root = Path(summary.get('original_experiment', directory))
    retries = {r['index']: Path(r['retry_directory']) for r in summary.get('retries', [])}
    results = []
    for worker in summary['workers']:
        policy = retries.get(worker['index'], root / f'worker-{worker["index"]:02d}')
        for episode in worker['episodes']: results.append(audit_episode(episode, policy))
    if len({r['run_id'] for r in results}) != len(results): raise ValueError('Repeated native game')
    counts = {k: Counter() for k in ('screens', 'events', 'warnings')}
    for row in results:
        for key, counter in counts.items(): counter.update(row[key])
    timings = sorted(t for r in results for t in r['decision_seconds'])
    return dict(experiment=str(directory.resolve()), completed=len(results),
        checked_decisions=sum(r['checked_decisions'] for r in results),
        threshold_card_takes=sum(r['threshold_card_takes'] for r in results),
        crisis_expansions=sum(r['crisis_expansions'] for r in results),
        decision_seconds_p95=timings[min(len(timings)-1, int(len(timings)*.95))] if timings else None,
        decision_seconds_max=max(timings) if timings else None,
        **{k: dict(v) for k, v in counts.items()}, games=results)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--experiment', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = audit_experiment(args.experiment)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    atomic_json(args.output, result)
    print(json.dumps({k: v for k, v in result.items() if k not in ('games', 'warnings')}, ensure_ascii=False))


if __name__ == '__main__': main()
