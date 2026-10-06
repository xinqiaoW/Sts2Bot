#!/usr/bin/env python3
"""Independently compare saved native checkpoint text with the historical plans."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import replay as r


def audit(batch):
    manifest = json.loads((batch / 'manifest.json').read_text())
    results = json.loads((batch / 'results.json').read_text())
    state = json.loads((batch / 'state.json').read_text())
    subjects = {c['sourceJobId']: c for c in manifest['cases']}
    if len(subjects) != len(manifest['cases']) or len(results) != len(subjects) or state.get('complete') is not True:
        raise ValueError('Batch scope is duplicated or incomplete')
    if {s['sourceJobId'] for s in results} != set(subjects) or len({s['sourceJobId'] for s in results}) != len(results):
        raise ValueError('Results do not match the selected historical case list')
    cases = []
    for summary in results:
        subject = subjects[summary['sourceJobId']]
        source = Path(subject['sourceAttemptPath'])
        for name, key in (('plan.json', 'sourcePlanSha256'), ('request.json', 'sourceRequestSha256')):
            if r.sha(source / name) != subject[key]:
                raise ValueError('Historical source changed: ' + str(source / name))
        original = json.loads((source / 'plan.json').read_text())
        out = Path(summary['outputPath'])
        plan = json.loads((out / 'plan.json').read_text())
        request = json.loads((out / 'request.json').read_text())
        native = json.loads((out / 'native-result.json').read_text())
        for key in ('sourceRunId', 'sourceJobId', 'progressSnapshotSha256', 'openingChoices',
                    'openingState', 'terminalState', 'plays', 'finishedTurn'):
            if plan[key] != original[key]:
                raise ValueError('Historical plan data differs: ' + key)
        expected_steps = original['steps']
        actual_steps = [{k: v for k, v in step.items() if k != 'terminalChoiceCancellation'} for step in plan['steps']]
        if expected_steps != actual_steps:
            raise ValueError('Historical action or boundary choices were changed')
        if request['runId'] != plan['nativeRunId'] or native['runId'] != plan['nativeRunId']:
            raise ValueError('Native result belongs to another request')
        expected = {'opening': original['openingState'], 'terminal': original['terminalState']}
        expected.update({f'after_play_{i}': step['expected'] for i, step in
                         enumerate(s for s in original['steps'] if s['kind'] == 'play')})
        checkpoint_path = out / 'checkpoints.jsonl'
        events = [json.loads(line) for line in checkpoint_path.read_text().splitlines()] if checkpoint_path.exists() else []
        if [e['sequence'] for e in events] != list(range(1, len(events) + 1)):
            raise ValueError('Incomplete native event sequence')
        checkpoints = [e['value'] for e in events if e['kind'] == 'checkpoint']
        seen = set()
        matched = 0
        for checkpoint in checkpoints:
            point = checkpoint['point']
            if point not in expected or point in seen:
                raise ValueError('Unexpected or repeated historical checkpoint: ' + point)
            seen.add(point)
            actual = checkpoint['actual']
            matches = actual == expected[point]
            if checkpoint['matches'] != matches:
                raise ValueError('Stored comparison flag differs from exact text comparison')
            for field, text in (('actualSha256', actual), ('expectedSha256', expected[point])):
                if checkpoint[field] != hashlib.sha256(text.encode()).hexdigest():
                    raise ValueError('Checkpoint hash differs from saved state text')
            matched += matches
        completed = [e['value'] for e in events if e['kind'] == 'replay_completed']
        complete = (len(completed) == 1 and seen == set(expected) and matched == len(expected)
                    and completed[0]['plays'] == original['plays']
                    and completed[0]['checkpoints'] == len(expected)
                    and completed[0]['finishedTurn'] == original['finishedTurn']
                    and completed[0]['nativeTerminalObserved'] is True
                    and completed[0]['noTeacherSearch'] is True)
        passed = native['status'] == 'Passed' and complete
        if summary['passed'] != passed or summary['comparisonCompleted'] != bool(completed):
            raise ValueError('Verification summary disagrees with native evidence')
        cases.append(dict(sourceJobId=summary['sourceJobId'], category=subject['category'],
                          nativeStatus=native['status'], passed=passed, comparisonCompleted=complete,
                          plays=original['plays'], checkpoints=len(checkpoints), matchedCheckpoints=matched,
                          stateMismatches=len(checkpoints) - matched, outputPath=str(out)))
    return dict(schema='native-fix-batch-audit/v1', total=len(cases), passed=sum(c['passed'] for c in cases),
                failed=sum(not c['passed'] for c in cases),
                comparisonCompleted=sum(c['comparisonCompleted'] for c in cases),
                plays=sum(c['plays'] for c in cases),
                matchedCheckpoints=sum(c['matchedCheckpoints'] for c in cases),
                stateMismatches=sum(c['stateMismatches'] for c in cases),
                categories=dict(Counter(c['category'] for c in cases)),
                nativeStatuses=dict(Counter(c['nativeStatus'] for c in cases)), cases=cases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--batch', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError('Refusing to overwrite an audit report')
    report = audit(args.batch)
    r.atomic_json(args.report, report)
    print(json.dumps({k: v for k, v in report.items() if k != 'cases'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
