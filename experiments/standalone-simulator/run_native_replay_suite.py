#!/usr/bin/env python3
"""Replay every checked-in native trace; compare full checkpoints and actual terminal metadata."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from replay_evidence import matched, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('host-dll', 'runtime', 'progress-snapshot', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--dotnet', required=True)
    parser.add_argument('--fixtures', type=Path, default=Path(__file__).with_name('fixtures'))
    args = parser.parse_args()
    if args.report.exists(): parser.error('Refusing to overwrite an existing report')
    paths = sorted(args.fixtures.glob('native-replay-*.json'))
    if not paths: parser.error('No native replay fixtures')
    folder = Path(tempfile.mkdtemp(prefix='native-replay-suite-'))
    report = dict(schema='native-replay-suite/v1', complete=False, passed=False,
                  productionReady=False, productionLabels=False, directory=str(folder),
                  hostSha256=hashlib.sha256(args.host_dll.read_bytes()).hexdigest(),
                  progressSnapshotSha256=hashlib.sha256(args.progress_snapshot.read_bytes()).hexdigest(),
                  scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), runs=[])
    write(args.report, report)
    for fixture in paths:
        source = json.loads(fixture.read_text())
        command = [args.dotnet, str(args.host_dll.resolve()), str(args.runtime.resolve()),
                   '--replay-native-request', str(fixture.resolve()), str(args.progress_snapshot.resolve())]
        log = folder / (fixture.stem + '.log')
        entry = dict(fixture=str(fixture.resolve()), fixtureSha256=hashlib.sha256(fixture.read_bytes()).hexdigest(),
                     command=command, log=str(log), passed=False)
        env = {**os.environ, 'DOTNET_TieredCompilation': '0'}
        env.pop('COMPlus_TieredCompilation', None)
        with log.open('w') as stream:
            try:
                entry['exitCode'] = subprocess.run(command, env=env, stdout=stream, stderr=subprocess.STDOUT, timeout=140).returncode
            except subprocess.TimeoutExpired:
                entry['error'] = 'Replay exceeded 140 seconds'
        values = []
        for line in log.read_text().splitlines():
            try: values.append(json.loads(line))
            except ValueError: pass
        terminals = [v for v in values if isinstance(v, dict) and v.get('status') == 'request_battle_completed']
        if len(terminals) == 1:
            result = terminals[0]
            entry['passed'] = entry.get('exitCode') == 0 and matched(source['nativeTrace'], result)
            battle = result.get('battle', {})
            entry.update(plays=battle.get('plays', 0), checkpoints=len(battle.get('compared', [])),
                         finalHp=result.get('finalHp'), finishedTurn=result.get('finishedTurn'))
        report['runs'].append(entry)
        write(args.report, report)
        print(json.dumps({k:entry[k] for k in ('fixture', 'passed')}), flush=True)
    report.update(complete=True, passed=all(r['passed'] for r in report['runs']),
                  totalPlays=sum(r.get('plays', 0) for r in report['runs']),
                  totalCheckpoints=sum(r.get('checkpoints', 0) for r in report['runs']))
    write(args.report, report)
    if not report['passed']: raise SystemExit(1)


if __name__ == '__main__':
    main()
