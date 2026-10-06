#!/usr/bin/env python3
"""Retained replay failures: representatives or every remaining related case.

Supply the read-only failure analysis and a freshly prepared isolated runtime.
The controller's full campaign and its frozen mod are never modified.
"""
import argparse
from collections import Counter
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import replay as r

CATEGORIES = ['opening_imbued_session', 'terminal_toasty_surface', 'terminal_entropy_accounting']


def remaining_cases(cases, previous):
    verified = {c['sourceJobId'] for c in previous
                if c.get('passed') is True and c.get('comparisonCompleted') is True
                and c.get('nativeStatus') == 'Passed'}
    selected = [c for c in cases if c['category'] in CATEGORIES and c['job'] not in verified]
    if len({c['job'] for c in selected}) != len(selected):
        raise ValueError('Duplicate historical case in remaining verification scope')
    return selected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--only', choices=CATEGORIES + ['negative_terminal'])
    mode.add_argument('--remaining-after', type=Path,
                      help='Exclude only native Passed comparisons in this previous summary')
    parser.add_argument('--batch-label', default='remaining', help='Unique output label for remaining cases')
    parser.add_argument('--expected-count', type=int, help='Reject an unexpected selected case count')
    args = parser.parse_args()
    config = json.loads((args.root / 'native-runtime.json').read_text())
    r.verify_inputs(args.root)
    cases = json.loads(args.analysis.read_text())['cases']
    if args.remaining_after:
        selected = remaining_cases(cases, json.loads(args.remaining_after.read_text()))
        if not args.batch_label or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.batch_label):
            parser.error('Batch label must contain only letters, numbers, underscores or hyphens')
        batch_root = args.root / 'fix-batches' / args.batch_label
        output = batch_root / 'results.json'
    else:
        selected = [next(c for c in cases if c['category'] == category) for category in CATEGORIES]
        selected.append({**selected[-1], 'category': 'negative_terminal'})
        if args.only:
            selected = [c for c in selected if c['category'] == args.only]
        batch_root = None
        output = args.root / ('verification-' + (args.only or 'all') + '.json')
    if args.expected_count is not None and len(selected) != args.expected_count:
        parser.error(f'Expected {args.expected_count} cases, selected {len(selected)}')
    if not selected:
        parser.error('No unverified cases were selected')
    lease = (args.root / 'fix-verification.lock').open('a')
    fcntl.flock(lease, fcntl.LOCK_EX | fcntl.LOCK_NB)
    if output.exists():
        raise FileExistsError('Refusing to overwrite an existing verification summary')
    if batch_root is not None:
        batch_root.mkdir(parents=True, exist_ok=False)
        r.atomic_json(batch_root / 'manifest.json', dict(
            analysisPath=str(args.analysis), analysisSha256=r.sha(args.analysis),
            previousSummary=str(args.remaining_after), previousSummarySha256=r.sha(args.remaining_after),
            runtimeManifestSha256=r.sha(args.root / 'manifest.json'),
            cases=[dict(sourceJobId=c['job'], category=c['category'], sourceAttemptPath=c['sourceAttemptPath'],
                        sourcePlanSha256=r.sha(Path(c['sourceAttemptPath']) / 'plan.json'),
                        sourceRequestSha256=r.sha(Path(c['sourceAttemptPath']) / 'request.json')) for c in selected]))
    sys.path.insert(0, str(r.COLLECTOR))
    from damage_model.worker import GameProcess
    process = GameProcess(config['game_dir'], config['data_dir'], config['command'],
                          config['env'], config['log_path'])
    summaries = []
    try:
        for index, case in enumerate(selected):
            out = (batch_root / case['category'] / case['job'] if batch_root is not None
                   else args.root / 'fix-cases' / case['category'])
            out.mkdir(parents=True, exist_ok=False)
            if batch_root is not None:
                r.atomic_json(batch_root / 'state.json', dict(total=len(selected), completed=len(summaries),
                    passed=sum(s['passed'] for s in summaries), activeJob=case['job'], activeOutput=str(out)))
            source = Path(case['sourceAttemptPath'])
            plan = json.loads((source / 'plan.json').read_text())
            r.annotate_terminal_cancellation(plan['steps'], plan['finishedTurn'])
            plan.update(nativeRunId=uuid.uuid4().hex, checkpointPath=str(out / 'checkpoints.jsonl'))
            negative = case['category'] == 'negative_terminal'
            if negative:
                plan['terminalState'] += '|deliberate-corruption'
            request = json.loads((source / 'request.json').read_text())
            request.update(runId=plan['nativeRunId'], timeoutSeconds=120, exitOnComplete=False)
            r.atomic_json(out / 'plan.json', plan)
            r.atomic_json(out / 'request.json', request)
            r.atomic_json(args.root / 'active-plan.json', plan)
            log_path = Path(config['log_path'])
            start = log_path.stat().st_size if log_path.exists() else 0
            result = process.run(request)
            r.atomic_json(out / 'native-result.json', result)
            with log_path.open('rb') as log:
                log.seek(start)
                with (out / 'native.log').open('wb') as saved:
                    saved.write(log.read()); saved.flush(); os.fsync(saved.fileno())
            checkpoint_path = out / 'checkpoints.jsonl'
            events = ([json.loads(line) for line in checkpoint_path.read_text().splitlines()]
                      if checkpoint_path.exists() else [])
            checks = [e['value'] for e in events if e['kind'] == 'checkpoint']
            completed = [e['value'] for e in events if e['kind'] == 'replay_completed']
            if negative:
                passed = (result['status'] == 'Failed' and not completed and len(checks) == plan['plays'] + 2
                          and all(c['matches'] for c in checks[:-1])
                          and checks[-1]['point'] == 'terminal' and checks[-1]['matches'] is False)
            else:
                passed = (result['status'] == 'Passed' and len(completed) == 1
                          and len(checks) == plan['plays'] + 2 and all(c['matches'] for c in checks))
            summary = dict(category=case['category'], sourceJobId=case['job'], outputPath=str(out),
                           sourceAttemptPath=str(source), sourcePlanSha256=r.sha(source / 'plan.json'),
                           nativeStatus=result['status'], passed=passed, checkpoints=len(checks),
                           comparisonCompleted=bool(completed),
                           stateMismatches=sum(c['matches'] is False for c in checks),
                           expectedCheckpoints=plan['plays'] + 2, nativeError=result.get('error'),
                           cancellations=[e['value'] for e in events if e['kind'] == 'recorded_terminal_plan_cancelled'])
            r.atomic_json(out / 'summary.json', summary)
            summaries.append(summary)
            # Preserve every completed outcome immediately, not just at shutdown.
            r.atomic_json(output, summaries)
            if batch_root is not None:
                r.event(batch_root / 'results.jsonl', summary)
                print(json.dumps(dict(completed=index + 1, total=len(selected), category=case['category'],
                    sourceJobId=case['job'], nativeStatus=result['status'], passed=passed,
                    checkpoints=len(checks), comparisonCompleted=bool(completed)), ensure_ascii=False), flush=True)
            else:
                print(json.dumps(summary, ensure_ascii=False), flush=True)
    finally:
        process.stop()
        subprocess.run([str(Path(config['command'][0]).with_name('wineserver')), '-k'],
                       env={**os.environ, 'WINEPREFIX': config['env']['WINEPREFIX']}, check=False)
        r.atomic_json(output, summaries)
        if batch_root is not None:
            r.atomic_json(batch_root / 'state.json', dict(total=len(selected), completed=len(summaries),
                passed=sum(s['passed'] for s in summaries), activeJob=None,
                complete=len(summaries) == len(selected),
                categories=dict(Counter(s['category'] for s in summaries)),
                nativeStatuses=dict(Counter(s['nativeStatus'] for s in summaries)),
                matchedCheckpoints=sum(s['checkpoints'] - s['stateMismatches'] for s in summaries),
                stateMismatches=sum(s['stateMismatches'] for s in summaries)))
    if not all(s['passed'] for s in summaries):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
