#!/usr/bin/env python3
"""Prove incorrect implicit choices and terminal RNG cannot pass native replay."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from replay_evidence import identity, write


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('host-dll', 'runtime', 'progress-snapshot', 'report'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--dotnet', required=True)
    args = parser.parse_args()
    if args.report.exists():
        parser.error('Refusing to overwrite an existing report')
    folder = Path(tempfile.mkdtemp(prefix='boundary-negative-suite-'))
    fixtures = Path(__file__).with_name('fixtures')
    report = dict(complete=False, passed=False, host=identity(args.host_dll),
                  script=identity(__file__), directory=str(folder), runs=[])
    for name, fixture_name, expected_error in (
        ('implicit-choice', 'native-replay-implicit-dual-wield.json', 'Recorded implicit choice failed validation'),
        ('terminal-rng', 'native-replay-wing-charm-terminal-rewards.json', 'Cross-runtime state differs at after_play_10'),
        ('cancelled-choice-terminal-hp', 'native-replay-terminal-enemy-choice-cancelled.json', 'Native fixed-action terminal differs'),
        ('end-turn-only-terminal-hp', 'native-replay-end-turn-only-victory.json', 'Native fixed-action terminal differs'),
        ('end-turn-only-state', 'native-replay-end-turn-only-victory.json', 'Cross-runtime state differs at end_turn_0'),
        ('terminal-sly-hp', 'native-replay-terminal-sly-setup-cancelled.json', 'Native fixed-action terminal differs'),
        ('terminal-sly-choice', 'native-replay-terminal-sly-setup-cancelled.json', 'INVALID_RECORDED_CARD'),
        ('terminal-sly-extra-action', 'native-replay-terminal-sly-setup-cancelled.json', 'PlannedCardSelector.AssertConsumed'),
    ):
        source = fixtures / fixture_name
        fixture = json.loads(source.read_text())
        events = fixture['nativeTrace']['events']
        if name == 'implicit-choice':
            event = next(e for e in events if e['kind'] == 'play' and e['value']['action']['CardId'] == 'DUAL_WIELD')
            token = event['value']['action']['Choice']['Cards'][0]
            assert token['CardId'] != 'STRIKE_SILENT'
            token['CardId'] = 'STRIKE_SILENT'
        elif name == 'terminal-rng':
            event = events[-1]
            assert event['kind'] == 'action_completed'
            left, right = event['value']['after'].rsplit('/', 1)
            counter, rest = right.split(':', 1)
            event['value']['after'] = left + '/' + str(int(counter) + 1) + ':' + rest
        elif name == 'end-turn-only-state':
            event = next(e for e in events if e['kind'] == 'end_turn')
            before = event['value']['before']
            event['value']['before'] = before.replace(';hp=70;', ';hp=69;', 1)
            assert event['value']['before'] != before
        elif name == 'terminal-sly-choice':
            event = events[-1]
            assert event['kind'] == 'choice_plan' and event['value']['owner'] == 'turn_setup:5'
            event['value']['choices'][0]['Cards'][0]['CardId'] = 'INVALID_RECORDED_CARD'
        elif name == 'terminal-sly-extra-action':
            # A later recorded action must prevent treating this boundary as final.
            value = next(e['value'] for e in reversed(events) if e['kind'] == 'play')
            events.append(dict(sequence=events[-1]['sequence'] + 1, kind='play', value=value))
        else:
            observation = fixture['nativeTrace']['result']['trainingObservation']
            expected_hp = {'cancelled-choice-terminal-hp': 0, 'end-turn-only-terminal-hp': 70,
                           'terminal-sly-hp': 58}[name]
            assert observation['finalHp'] == expected_hp
            wrong_hp = 1 if expected_hp == 0 else expected_hp - 1
            observation.update(finalHp=wrong_hp, netHpLoss=observation['initialHp'] - wrong_hp, playerDied=False)
        changed = folder / (name + '.json')
        write(changed, fixture)
        log = folder / (name + '.log')
        command = [args.dotnet, str(args.host_dll.resolve()), str(args.runtime.resolve()),
                   '--replay-native-request', str(changed), str(args.progress_snapshot.resolve())]
        with log.open('x') as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=140)
        log_text = log.read_text()
        records = [json.loads(line) for line in log_text.splitlines() if line.startswith('{')]
        def expected_failure(record):
            if record.get('status') != 'blocked':
                return False
            error = record.get('error', '')
            # Queue draining may propagate the original selector exception
            # before the observer adds its context. Both reject this exact token.
            return (expected_error in error or (name == 'implicit-choice'
                    and '找不到 STRIKE_SILENT+0#0' in error
                    and 'PlannedCardSelector.GetSelectedCards' in error)
                    or (name == 'terminal-sly-choice'
                        and 'Native combat loop did not reach playable turn' in error
                        # Original async hooks log the selector exception before
                        # the bounded host wait fails. Require that exact cause;
                        # an unrelated timeout is not evidence of rejection.
                        and '自动选牌时找不到 INVALID_RECORDED_CARD+0#0' in log_text
                        and 'CombatSolver.PlannedCardSelector.GetSelectedCards' in log_text))
        rejected = (result.returncode == 1
                    and not any(r.get('status') == 'request_battle_completed' for r in records)
                    and any(expected_failure(r) for r in records))
        report['runs'].append(dict(name=name, source=identity(source), changed=identity(changed),
                                   log=identity(log), command=command, exitCode=result.returncode, rejected=rejected))
        write(args.report, report)
    report.update(complete=True, passed=all(r['rejected'] for r in report['runs']))
    write(args.report, report)
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
