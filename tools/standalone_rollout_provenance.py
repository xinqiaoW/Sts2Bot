"""Bind a rollout to completed full-state acceptance and its native observer."""
from pathlib import Path

from standalone_rollout_metrics import identity, read, sha


def require(condition, message):
    if not condition:
        raise ValueError(message)


def checked_identity(entry):
    require(identity(entry['path']) == entry, 'Frozen evidence changed: ' + entry['path'])


def verify_correctness(audit_path, bundle, prior_plan):
    """Consume the independent audit, never a runner's progress/pass summary."""
    bundle = Path(bundle)
    report = read(audit_path)
    require(report.get('schema') == 'distinct-build-panel-audit/v1' and report.get('passed') is True,
            'Completed independent build audit required')
    require(report['requiredValidatedBuilds'] >= 10000 and report['uniqueBuilds'] >= report['requiredValidatedBuilds']
            and report['uniqueTargets'] == 80 and report['matchedCheckpoints'] >= report['checkpointTarget'] >= 500000,
            'Correctness acceptance thresholds not met')
    require(report.get('campaignDrained') is True and report['unexecutedCases'] >= 0 and not any(report[k] for k in
            ('unresolvedReplayDifferences', 'staleHostResults')),
            'Correctness campaign is still active or has divergent cases')
    require(report['panelValidation']['passed'] is True, 'Frozen build panel was not validated')
    require(report['plan'] == identity(prior_plan), 'Excluded builds differ from the accepted panel')
    for key in ('host', 'progressSnapshot', 'plan', 'auditor'):
        checked_identity(report[key])
    teacher = read(bundle / 'teacher.json')
    require(report['teacher'] == read(bundle / 'configs/teacher.json')
            and all(teacher.get(k) == v for k, v in report['teacher'].items()),
            'Accepted native teacher differs from release')
    require(report['host']['sha256'] == sha(bundle / 'host/SimulatorPrototype.dll')
            == teacher['standalone_host_sha256'], 'Accepted host differs from release')
    require(report['progressSnapshot']['sha256'] == sha(bundle / 'progress-snapshot.json')
            == teacher['progress_snapshot_sha256'], 'Accepted progress snapshot differs from release')
    runs = report['runs']
    # Exhausted native captures remain explicit failures and contribute no builds
    # or checkpoints; the independent audit must still prove >= 10,000 builds.
    require(len(runs) == report['matchedBattles']
            and len(runs) + len(report['nativeCaptureFailures']) + report['unexecutedCases'] == report['plannedCases']
            and len({r['caseId'] for r in runs}) == len(runs), 'Audit case accounting differs')
    require(sum(r['checkpoints'] for r in runs) == report['matchedCheckpoints'],
            'Audit checkpoint accounting differs')
    require(all(r.get('terminalStateVerified') is True and r.get('playPileStateVerified') is True
                and r.get('terminalCheckpoints') == 1 for r in runs),
            'Every battle must verify terminal state and ordered PlayPile')
    for run in runs:
        checked_identity(run['result'])
    return report


def verify_benchmark(entry, report):
    checked_identity(entry)
    benchmark = read(entry['path'])
    require(benchmark.get('schema') == 'standalone-paired-cold/v1' and benchmark.get('complete') is True,
            'Completed paired benchmark required')
    require(benchmark['hostSha256'] == report['host']['sha256']
            and benchmark['nativeTeacher'] == report['teacher']
            and benchmark['progressSnapshotSha256'] == report['progressSnapshot']['sha256'],
            'Benchmark candidate differs from accepted candidate')
    expected = {(repeat, fixture, backend)
                for repeat in range(1, benchmark['repeats'] + 1)
                for fixture in benchmark['fixtureHashes']
                for backend in ('native-wine', 'standalone-managed-native')}
    trials = benchmark['trials']
    require(benchmark['repeats'] >= 2 and expected and len(trials) == len(expected)
            and {(t['repeat'], t['fixture'], t['backend']) for t in trials} == expected,
            'Benchmark is missing paired trials')
    require(all(t['validatedStatus'] == 'complete' and t.get('cpuIsolationVerified') is True for t in trials),
            'Benchmark has failed trials or unverified CPU isolation')
    for trial in trials:
        checked_identity({'path': str(Path(trial['resultFile']).resolve()), 'sha256': trial['resultSha256']})
    # Independent searches can produce different labels. Their equality is not
    # the correctness gate; it is checked by fixed-action replay above.


def native_files(source):
    source = Path(source)
    paths = [source / 'configs/teacher.json',
             source / 'experiments/native-trace-probe/NativeTraceProbe.json']
    paths += [p for base in ('damage_model', 'experiments/native-trace-probe')
              for p in (source / base).rglob('*.py')]
    return {str(p.relative_to(source)): sha(p) for p in sorted(paths)}


def verify_candidate(plan):
    checked_identity(plan['correctnessAudit'])
    report = verify_correctness(plan['correctnessAudit']['path'], plan['bundle'], plan['priorPlan']['path'])
    verify_benchmark(plan['benchmark'], report)
    checked_identity(plan['priorPlan'])
    checked_identity(plan['nativeRuntimeIdentity'])
    require(str(Path(plan['nativeRuntime']).resolve()) == plan['nativeRuntimeIdentity']['path'],
            'Native runtime path differs from its frozen identity')
    checked_identity(plan['traceDll'])
    source = Path(plan['nativeSource'])
    require(native_files(source) == plan['nativeFiles'], 'Native recorder source or configuration changed')
    require(read(source / 'configs/teacher.json') == report['teacher'],
            'Native audit teacher differs from accepted teacher')
    runtime = read(plan['nativeRuntime'])
    require(runtime.get('backend', 'native-wine') == 'native-wine', 'Native audit requires native runtime')
    game = Path(runtime['game_dir'])
    for key, name in (
        ('game_sha256', 'data_sts2_windows_x86_64/sts2.dll'),
        ('collector_sha256', 'mods/CombatSolver/CombatSolver.dll'),
        ('ritsu_sha256', 'mods/STS2-RitsuLib/STS2-RitsuLib.dll'),
    ):
        require(sha(game / name) == report['teacher'][key], 'Native runtime provenance mismatch: ' + key)
    return report
