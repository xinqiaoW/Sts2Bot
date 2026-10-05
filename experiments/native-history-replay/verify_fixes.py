#!/usr/bin/env python3
"""One retained failure per replay bug, plus a corrupt-terminal negative control.

Supply the read-only failure analysis and a freshly prepared isolated runtime.
The controller's full campaign and its frozen mod are never modified.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid

import replay as r


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--analysis', type=Path, required=True)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--only', choices=['opening_imbued_session', 'terminal_toasty_surface',
                                         'terminal_entropy_accounting', 'negative_terminal'])
    args = parser.parse_args()
    config = json.loads((args.root / 'native-runtime.json').read_text())
    r.verify_inputs(args.root)
    cases = json.loads(args.analysis.read_text())['cases']
    categories = ['opening_imbued_session', 'terminal_toasty_surface', 'terminal_entropy_accounting']
    selected = [next(c for c in cases if c['category'] == category) for category in categories]
    selected.append({**selected[-1], 'category': 'negative_terminal'})
    if args.only:
        selected = [c for c in selected if c['category'] == args.only]
    sys.path.insert(0, str(r.COLLECTOR))
    from damage_model.worker import GameProcess
    process = GameProcess(config['game_dir'], config['data_dir'], config['command'],
                          config['env'], config['log_path'])
    summaries = []
    try:
        for case in selected:
            out = args.root / 'fix-cases' / case['category']
            out.mkdir(parents=True, exist_ok=False)
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
            events = [json.loads(line) for line in (out / 'checkpoints.jsonl').read_text().splitlines()]
            checks = [e['value'] for e in events if e['kind'] == 'checkpoint']
            completed = [e['value'] for e in events if e['kind'] == 'replay_completed']
            if negative:
                passed = (result['status'] == 'Failed' and not completed and len(checks) == plan['plays'] + 2
                          and all(c['matches'] for c in checks[:-1])
                          and checks[-1]['point'] == 'terminal' and checks[-1]['matches'] is False)
            else:
                passed = (result['status'] == 'Passed' and len(completed) == 1
                          and len(checks) == plan['plays'] + 2 and all(c['matches'] for c in checks))
            summary = dict(category=case['category'], sourceJobId=case['job'],
                           sourceAttemptPath=str(source), sourcePlanSha256=r.sha(source / 'plan.json'),
                           nativeStatus=result['status'], passed=passed, checkpoints=len(checks),
                           comparisonCompleted=bool(completed),
                           cancellations=[e['value'] for e in events if e['kind'] == 'recorded_terminal_plan_cancelled'])
            r.atomic_json(out / 'summary.json', summary)
            summaries.append(summary)
            print(json.dumps(summary, ensure_ascii=False), flush=True)
    finally:
        process.stop()
        subprocess.run([str(Path(config['command'][0]).with_name('wineserver')), '-k'],
                       env={**os.environ, 'WINEPREFIX': config['env']['WINEPREFIX']}, check=False)
        r.atomic_json(args.root / ('verification-' + (args.only or 'all') + '.json'), summaries)
    if not all(s['passed'] for s in summaries):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
