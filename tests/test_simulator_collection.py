"""Simulator entry-point wiring on temporary releases and collection directories."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from damage_model.provenance import sha256
from tools import collect_simulator as simulator


@pytest.fixture
def bundle(tmp_path, monkeypatch):
    root = tmp_path / 'release'
    names = ('host/SimulatorPrototype.dll', 'host/SimulatorPrototype.runtimeconfig.json',
             'host/SimulatorPrototype.deps.json', 'progress-snapshot.json',
             'catalogs/game-0.111.0.raw.json', 'configs/real-runs-8s.json',
             'configs/mutations-8s.json', 'configs/mutations-targeted-8s.json')
    for name in names:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{}')
    teacher = {'execution_backend': 'standalone-managed-native'}
    runtime = {'backend': 'standalone-managed-native', 'game_dir': str(tmp_path / 'game'),
               'dotnet': str(tmp_path / 'dotnet')}
    for name, value in (('teacher.json', teacher), ('runtime-template.json', runtime)):
        (root / name).write_text(json.dumps(value))
    files = {str(path.relative_to(root)): sha256(path) for path in root.rglob('*') if path.is_file()}
    (root / 'release.json').write_text(json.dumps({
        'schema': 'standalone-collector-release/v1', 'teacher': teacher, 'files': files}))
    monkeypatch.setattr(simulator, 'verify_runtime', lambda runtime, teacher: None)
    return root


def test_prepare_resumes_private_queues_and_allocates_distinct_workers(bundle, tmp_path):
    directory = tmp_path / 'instance'
    args = simulator.prepare(bundle, directory, workers=2)
    assert args.collect_only is True
    assert args.teacher == str(bundle / 'teacher.json')
    assert args.catalog == str(bundle / 'catalogs/game-0.111.0.raw.json')
    runtimes = [json.loads(Path(path).read_text()) for path in args.runtimes]
    assert len({runtime['data_dir'] for runtime in runtimes}) == 2
    for runtime in runtimes:
        assert runtime['backend'] == 'standalone-managed-native'
        assert 'WINEPREFIX' not in runtime['env']
        assert Path(runtime['data_dir']).is_relative_to(directory)
        assert Path(runtime['env']['TMPDIR']).is_relative_to(directory)
    Path(args.db).write_bytes(b'preserved collection')
    assert vars(simulator.prepare(bundle, directory, workers=2)) == vars(args)
    assert Path(args.db).read_bytes() == b'preserved collection'
    with pytest.raises(ValueError, match='worker count changed'):
        simulator.prepare(bundle, directory, workers=3)


def test_release_corruption_is_rejected_before_creating_collection(bundle, tmp_path):
    (bundle / 'host/SimulatorPrototype.dll').write_text('changed')
    directory = tmp_path / 'instance'
    with pytest.raises(ValueError, match='file changed'):
        simulator.prepare(bundle, directory)
    assert not directory.exists()


@pytest.mark.parametrize('change', ['pointer', 'runtime', 'existing-files'])
def test_prepare_rejects_changed_or_foreign_collection_directory(bundle, tmp_path, change):
    directory = tmp_path / 'instance'
    if change == 'existing-files':
        directory.mkdir()
        (directory / 'important.txt').write_text('preserve me')
    else:
        args = simulator.prepare(bundle, directory)
        path = directory / 'active-collection.json' if change == 'pointer' else Path(args.runtimes[0])
        path.write_text('{}')
    with pytest.raises(ValueError):
        simulator.prepare(bundle, directory)
    if change == 'existing-files':
        assert (directory / 'important.txt').read_text() == 'preserve me'


def test_single_pass_passes_simulator_teacher_and_catalog_to_worker_pool(bundle, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('PYTHONPATH', 'original-path')
    events = []
    class Controller:
        def __init__(self, args):
            self.args = args
            self.stop_requested = False
            self.store = SimpleNamespace(db=SimpleNamespace(close=lambda: events.append('closed')))
            self.mutation_store = self.targeted_store = None
        def guard(self): events.append('guard')
        def refill(self): events.append('refill')
        def refill_mutations(self): events.append('mutations')
        def work_counts(self): return {'complete': 1}
    monkeypatch.setattr(simulator, 'Controller', Controller)
    def run(command, **kwargs):
        assert command[command.index('--teacher') + 1] == str(bundle / 'teacher.json')
        assert command[command.index('--catalog') + 1] == str(bundle / 'catalogs/game-0.111.0.raw.json')
        assert command[command.index('--limit-per-worker') + 1] == '1'
        assert '--train-after' not in command
        assert kwargs['check'] is True
        events.append('pool')
    monkeypatch.setattr(simulator.subprocess, 'run', run)
    simulator.main(['--bundle', str(bundle), '--directory', 'instance'])
    assert events == ['guard', 'refill', 'pool', 'mutations', 'closed']
    assert Path.cwd() == tmp_path
    import os
    assert os.environ['PYTHONPATH'] == 'original-path'


def test_continuous_exit_keeps_ownership_until_pool_drains(bundle, tmp_path, monkeypatch):
    directory = tmp_path / 'instance'
    events = []
    class Child:
        finished = False
        def poll(self): return 0 if self.finished else None
        def wait(self, timeout):
            with simulator.exclusive(directory / 'db/real.continuous.lock') as held:
                assert not held
            assert (directory / 'worker-01/collector.stop').exists()
            self.finished = True
            events.append('drained')
    class Controller:
        def __init__(self, args):
            self.child = Child()
            self.store = SimpleNamespace(db=SimpleNamespace(close=lambda: events.append('closed')))
            self.mutation_store = self.targeted_store = None
        def run(self): events.append('run')
    monkeypatch.setattr(simulator, 'Controller', Controller)
    simulator.main(['--bundle', str(bundle), '--directory', str(directory), '--continuous'])
    assert events == ['run', 'drained', 'closed']
    with simulator.exclusive(directory / 'db/real.continuous.lock') as held:
        assert held
