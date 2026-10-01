"""A changed candidate or incomplete/old audit must not authorize collection."""
import copy
import json
from pathlib import Path
import shutil
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from standalone_rollout_metrics import identity, read, sha, write
from standalone_rollout_provenance import native_files, verify_candidate, verify_correctness, verify_benchmark


@pytest.fixture(scope='module')
def accepted(tmp_path_factory):
    # Synthetic evidence tests the launch gate; it is never campaign acceptance.
    root = tmp_path_factory.mktemp('synthetic-acceptance')
    bundle = root / 'bundle'
    (bundle / 'host').mkdir(parents=True)
    (bundle / 'configs').mkdir()
    (bundle / 'host/SimulatorPrototype.dll').write_bytes(b'unit-host')
    (bundle / 'progress-snapshot.json').write_text('{}')
    teacher = dict(collector_sha256='c' * 64, game_sha256='g' * 64, ritsu_sha256='r' * 64)
    write(bundle / 'configs/teacher.json', teacher)
    write(bundle / 'teacher.json', {**teacher,
          'standalone_host_sha256': sha(bundle / 'host/SimulatorPrototype.dll'),
          'progress_snapshot_sha256': sha(bundle / 'progress-snapshot.json')})
    write(root / 'plan.json', {'teacher': teacher})
    (root / 'auditor.py').write_text('# synthetic auditor identity')
    results = root / 'results'; results.mkdir()
    runs = []
    for i in range(10000):
        result = results / f'{i}.json'
        result.write_text(json.dumps({'caseId': str(i)}))
        runs.append(dict(caseId=str(i), checkpoints=50, result=identity(result),
                         terminalStateVerified=True, playPileStateVerified=True, terminalCheckpoints=1))
    report = dict(schema='distinct-build-panel-audit/v1', passed=True, requiredValidatedBuilds=10000,
                  uniqueBuilds=10000, uniqueTargets=80, matchedCheckpoints=500000, checkpointTarget=500000,
                  unexecutedCases=0, campaignDrained=True, unresolvedReplayDifferences=[], nativeCaptureFailures=[], staleHostResults=[],
                  panelValidation={'passed': True}, plan=identity(root / 'plan.json'), auditor=identity(root / 'auditor.py'),
                  host=identity(bundle / 'host/SimulatorPrototype.dll'), teacher=teacher,
                  progressSnapshot=identity(bundle / 'progress-snapshot.json'), runs=runs,
                  matchedBattles=10000, plannedCases=10000)
    return root, report


def save_audit(tmp_path, report):
    path = tmp_path / 'audit.json'; write(path, report); return path


def test_complete_current_audit_authorizes_only_matching_release(accepted, tmp_path):
    root, report = accepted
    assert verify_correctness(save_audit(tmp_path, report), root / 'bundle', root / 'plan.json')['passed']


@pytest.mark.parametrize('mutation', [
    'runner_report', 'not_passed', 'too_few_builds', 'too_few_targets', 'too_few_points', 'relaxed_target',
    'unaccounted', 'still_active', 'difference', 'native_failed', 'stale', 'old_terminal', 'old_playpile',
    'duplicate_case', 'inflated_points', 'different_teacher', 'missing_progress',
])
def test_partial_historical_or_inconsistent_audit_cannot_authorize(accepted, tmp_path, mutation):
    root, original = accepted
    report = copy.deepcopy(original)
    if mutation == 'runner_report': report['schema'] = 'broad-native-parity/v1'
    elif mutation == 'not_passed': report['passed'] = False
    elif mutation == 'too_few_builds': report['uniqueBuilds'] = 9999
    elif mutation == 'too_few_targets': report['uniqueTargets'] = 79
    elif mutation == 'too_few_points': report['matchedCheckpoints'] = 499999
    elif mutation == 'relaxed_target': report['checkpointTarget'] = 1
    elif mutation == 'unaccounted': report['unexecutedCases'] = 1
    elif mutation == 'still_active': report['campaignDrained'] = False
    elif mutation == 'difference': report['unresolvedReplayDifferences'] = ['failed']
    elif mutation == 'native_failed': report['nativeCaptureFailures'] = ['failed']
    elif mutation == 'stale': report['staleHostResults'] = ['old']
    elif mutation == 'old_terminal': report['runs'][0]['terminalStateVerified'] = False
    elif mutation == 'old_playpile': report['runs'][0].pop('playPileStateVerified')
    elif mutation == 'duplicate_case': report['runs'][1]['caseId'] = report['runs'][0]['caseId']
    elif mutation == 'inflated_points': report['matchedCheckpoints'] += 1
    elif mutation == 'different_teacher': report['teacher']['collector_sha256'] = 'old'
    elif mutation == 'missing_progress': report.pop('progressSnapshot')
    with pytest.raises((ValueError, KeyError)):
        verify_correctness(save_audit(tmp_path, report), root / 'bundle', root / 'plan.json')


@pytest.mark.parametrize('changed', ['host/SimulatorPrototype.dll', 'progress-snapshot.json'])
def test_rebuilt_host_or_progress_cannot_reuse_acceptance(accepted, tmp_path, changed):
    root, report = accepted
    bundle = tmp_path / 'bundle'; shutil.copytree(root / 'bundle', bundle)
    (bundle / changed).write_bytes(b'new candidate')
    with pytest.raises(ValueError, match='differs from release'):
        verify_correctness(save_audit(tmp_path, report), bundle, root / 'plan.json')


def test_changed_result_receipt_cannot_reuse_acceptance(accepted, tmp_path):
    root, original = accepted; report = copy.deepcopy(original)
    result = tmp_path / 'result.json'; result.write_text('{}')
    report['runs'][0]['result'] = identity(result)
    result.write_text('{"changed":true}')
    with pytest.raises(ValueError, match='Frozen evidence changed'):
        verify_correctness(save_audit(tmp_path, report), root / 'bundle', root / 'plan.json')


def test_drained_ten_thousand_builds_do_not_require_unused_reserve_inputs(accepted, tmp_path):
    root, original = accepted; report = copy.deepcopy(original)
    report.update(plannedCases=10500, unexecutedCases=498,
                  nativeCaptureFailures=[{'caseId': 'native-failed-1'}, {'caseId': 'native-failed-2'}])
    assert verify_correctness(save_audit(tmp_path, report), root / 'bundle', root / 'plan.json')['passed']


def benchmark_for(tmp_path, report):
    trials = []
    for repeat in (1, 2):
        for backend in ('native-wine', 'standalone-managed-native'):
            result = tmp_path / f'{repeat}-{backend}.json'; write(result, {'unit': True})
            trials.append(dict(repeat=repeat, fixture='unit', backend=backend, validatedStatus='complete',
                               cpuIsolationVerified=True, resultFile=str(result), resultSha256=sha(result)))
    benchmark = tmp_path / 'benchmark.json'
    write(benchmark, dict(schema='standalone-paired-cold/v1', complete=True, hostSha256=report['host']['sha256'],
                          nativeTeacher=report['teacher'], progressSnapshotSha256=report['progressSnapshot']['sha256'],
                          repeats=2, fixtureHashes={'unit': 'hash'}, trials=trials,
                          pairs=[{'matched': False}]))
    return identity(benchmark)


def test_independent_search_labels_need_not_match(accepted, tmp_path):
    _, report = accepted
    verify_benchmark(benchmark_for(tmp_path, report), report)


@pytest.mark.parametrize('change', ['incomplete', 'old_host', 'old_teacher', 'old_progress', 'failed_trial',
                                   'missing_trial', 'cpu_contention', 'changed_result'])
def test_benchmark_must_measure_current_accepted_candidate(accepted, tmp_path, change):
    _, report = accepted
    entry = benchmark_for(tmp_path, report); data = read(entry['path'])
    if change == 'incomplete': data['complete'] = False
    elif change == 'old_host': data['hostSha256'] = 'old'
    elif change == 'old_teacher': data['nativeTeacher']['collector_sha256'] = 'old'
    elif change == 'old_progress': data['progressSnapshotSha256'] = 'old'
    elif change == 'failed_trial': data['trials'][0]['validatedStatus'] = 'failed'
    elif change == 'missing_trial': data['trials'].pop()
    elif change == 'cpu_contention': data['trials'][0]['cpuIsolationVerified'] = False
    elif change == 'changed_result': Path(data['trials'][0]['resultFile']).write_text('{}')
    write(entry['path'], data)
    with pytest.raises(ValueError):
        verify_benchmark(identity(entry['path']), report)


@pytest.fixture
def candidate(accepted, tmp_path):
    root, original = accepted
    report = copy.deepcopy(original)
    bundle = tmp_path / 'bundle'; shutil.copytree(root / 'bundle', bundle)
    native = tmp_path / 'native'
    game = tmp_path / 'game'
    teacher = {}
    for key, name in [('game_sha256', 'data_sts2_windows_x86_64/sts2.dll'),
                      ('collector_sha256', 'mods/CombatSolver/CombatSolver.dll'),
                      ('ritsu_sha256', 'mods/STS2-RitsuLib/STS2-RitsuLib.dll')]:
        path = game / name; path.parent.mkdir(parents=True); path.write_bytes(key.encode())
        teacher[key] = sha(path)
    report['teacher'] = teacher
    write(bundle / 'configs/teacher.json', teacher)
    write(bundle / 'teacher.json', {**read(bundle / 'teacher.json'), **teacher})
    write(native / 'configs/teacher.json', teacher)
    write(native / 'experiments/native-trace-probe/NativeTraceProbe.json', {'id': 'probe'})
    (native / 'experiments/native-trace-probe/persistent_capture_v2.py').write_text('class PersistentCapture: pass\n')
    runtime = tmp_path / 'runtime.json'; write(runtime, {'game_dir': str(game)})
    trace = tmp_path / 'probe.dll'; trace.write_bytes(b'probe')
    return dict(bundle=str(bundle), correctnessAudit=identity(save_audit(tmp_path, report)),
                benchmark=benchmark_for(tmp_path, report),
                priorPlan=identity(root / 'plan.json'), nativeSource=str(native), nativeFiles=native_files(native),
                nativeRuntime=str(runtime), nativeRuntimeIdentity=identity(runtime), traceDll=identity(trace))


def test_candidate_checks_native_dependencies_before_collection(candidate):
    assert verify_candidate(candidate)['passed']


def test_canonical_recorder_imports_without_legacy_filename(candidate):
    source = Path(candidate['nativeSource'])
    legacy = source / 'experiments/native-trace-probe/persistent_capture_v2.py'
    legacy.rename(legacy.with_name('persistent_capture.py'))
    candidate['nativeFiles'] = native_files(source)
    assert verify_candidate(candidate)['passed']


@pytest.mark.parametrize('contents', [None, 'import missing_native_recorder_dependency\n', '# no capture class\n'])
def test_recorder_import_failure_rejects_candidate_before_collection(candidate, contents):
    source = Path(candidate['nativeSource'])
    path = source / 'experiments/native-trace-probe/persistent_capture_v2.py'
    path.unlink()
    if contents is not None:
        path.with_name('persistent_capture.py').write_text(contents)
    candidate['nativeFiles'] = native_files(source)
    with pytest.raises(ValueError, match='Native recorder import preflight failed'):
        verify_candidate(candidate)


def test_recorder_load_ignores_ambient_same_named_module(candidate, monkeypatch):
    import types
    from standalone_rollout_provenance import load_native_capture
    monkeypatch.setitem(sys.modules, 'persistent_capture_v2', types.SimpleNamespace(PersistentCapture='wrong'))
    capture = load_native_capture(candidate)
    assert callable(capture) and capture.__module__ == 'frozen_rollout_native_capture'


@pytest.mark.parametrize('change', ['runtime', 'runtime_path', 'trace', 'teacher_config', 'probe_config', 'recorder', 'native_solver', 'audit'])
def test_changed_native_inputs_reject_launch(candidate, change, tmp_path):
    source = Path(candidate['nativeSource'])
    path = {
        'runtime': Path(candidate['nativeRuntime']),
        'runtime_path': tmp_path / 'other-runtime.json',
        'trace': Path(candidate['traceDll']['path']),
        'teacher_config': source / 'configs/teacher.json',
        'probe_config': source / 'experiments/native-trace-probe/NativeTraceProbe.json',
        'recorder': source / 'experiments/native-trace-probe/persistent_capture_v2.py',
        'native_solver': tmp_path / 'game/mods/CombatSolver/CombatSolver.dll',
        'audit': Path(candidate['correctnessAudit']['path']),
    }[change]
    path.write_bytes(b'changed')
    if change == 'runtime_path': candidate['nativeRuntime'] = str(path)
    with pytest.raises(ValueError):
        verify_candidate(candidate)


def test_controller_rejects_old_plan_before_starting_workers(tmp_path):
    from run_standalone_rollout import verify_plan
    write(tmp_path / 'plan.json', {'schema': 'standalone-rollout/v1'})
    with pytest.raises(ValueError, match='full-state correctness binding'):
        verify_plan(tmp_path)
