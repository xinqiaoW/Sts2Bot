import importlib.util
from pathlib import Path
import sys

source = Path(__file__).resolve().parents[1] / 'experiments/standalone-simulator'
sys.path.insert(0, str(source))
spec = importlib.util.spec_from_file_location('backend_comparison', source / 'run_backend_comparison.py')
benchmark = importlib.util.module_from_spec(spec)
spec.loader.exec_module(benchmark)
sys.path.remove(str(source))


def test_failed_attempts_stay_in_throughput_denominator():
    trials = [
        dict(backend='native-wine', validatedStatus='complete', wallSeconds=30),
        dict(backend='native-wine', validatedStatus='failed', wallSeconds=90),
        dict(backend='standalone-managed-native', validatedStatus='complete', wallSeconds=10),
        dict(backend='standalone-managed-native', validatedStatus='complete', wallSeconds=20),
    ]
    result = benchmark.summarize(trials)
    assert result['native-wine']['validLabelsPerHour'] == 30
    assert result['native-wine']['failed'] == 1
    assert result['native-wine']['p95WallSeconds'] == 90
    assert result['standalone-managed-native']['validLabelsPerHour'] == 240
    assert result['coldMedianSpeedRatio'] == 4
    assert result['validLabelThroughputRatio'] == 8
    assert result['coldMedianTimeReductionPercent'] == 75


def test_unbalanced_partial_run_does_not_report_speed_ratio():
    trials = [dict(backend='native-wine', validatedStatus='complete', wallSeconds=30),
              dict(backend='standalone-managed-native', validatedStatus='failed', wallSeconds=10),
              dict(backend='standalone-managed-native', validatedStatus='complete', wallSeconds=20)]
    assert 'coldMedianSpeedRatio' not in benchmark.summarize(trials)


def test_affinity_violation_suppresses_speed_claim():
    trials = [dict(backend='native-wine', validatedStatus='complete', wallSeconds=30, cpuIsolationVerified=False),
              dict(backend='standalone-managed-native', validatedStatus='complete', wallSeconds=10, cpuIsolationVerified=True)]
    assert 'coldMedianSpeedRatio' not in benchmark.summarize(trials)


def test_warm_batches_never_interleave_live_backends():
    schedule=list(benchmark.trial_schedule(['a','b','c'], 2, 'warm-native-batch'))
    assert [row[2] for row in schedule] == ['native-wine']*3+['standalone-managed-native']*6+['native-wine']*3
    assert [row[1] for row in schedule] == ['a','b','c']*4
    assert [row[3] for row in schedule] == [False,False,True]*4


def test_cold_pairs_alternate_order_and_always_stop():
    schedule=list(benchmark.trial_schedule(['a','b'], 1, 'cold'))
    assert [row[2] for row in schedule] == ['native-wine','standalone-managed-native','standalone-managed-native','native-wine']
    assert all(row[3] for row in schedule)


def test_warm_summary_is_not_labeled_cold():
    trials=[dict(backend='native-wine',validatedStatus='complete',wallSeconds=10),
            dict(backend='standalone-managed-native',validatedStatus='complete',wallSeconds=5)]
    summary=benchmark.summarize(trials,'warm-native-batch')
    assert summary['batchMedianSpeedRatio']==2
    assert summary['totalMeasuredTimeRatio']==2
    assert 'coldMedianSpeedRatio' not in summary


def test_reused_failure_remains_identified_after_process_is_stopped(tmp_path, monkeypatch):
    from types import SimpleNamespace
    game = benchmark.ObservedGameProcess(tmp_path, tmp_path / 'data', ['unused'])
    game.process = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(benchmark.GameProcess, 'stop', lambda self: setattr(self, 'process', None))
    def fail(self, request):
        self.stop()
        return {'status': 'Failed'}
    monkeypatch.setattr(benchmark.GameProcess, 'run', fail)
    assert game.run({})['status'] == 'Failed'
    assert game.process is None and game.request_process_reused is True


def test_ready_handshake_restart_is_not_counted_as_reuse(tmp_path, monkeypatch):
    from types import SimpleNamespace
    game = benchmark.ObservedGameProcess(tmp_path, tmp_path / 'data', ['unused'])
    game.process = SimpleNamespace(poll=lambda: None)
    monkeypatch.setattr(benchmark.GameProcess, 'start', lambda self: setattr(self, 'process', SimpleNamespace(poll=lambda: None)))
    def restart(self, request):
        self.process = None
        self.start()
        return {'status': 'Passed'}
    monkeypatch.setattr(benchmark.GameProcess, 'run', restart)
    game.run({})
    assert game.request_process_reused is False
