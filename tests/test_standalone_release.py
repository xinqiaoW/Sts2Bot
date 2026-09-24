import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest

source = Path(__file__).resolve().parents[1] / 'experiments/standalone-simulator/release_tool.py'
spec = importlib.util.spec_from_file_location('release_tool', source)
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


@pytest.fixture
def bundle(tmp_path):
    files = {}
    for name in ('release_tool.py', 'teacher.json', 'runtime-template.json', 'host/SimulatorPrototype.dll',
                 'host/SimulatorPrototype.runtimeconfig.json', 'host/SimulatorPrototype.deps.json',
                 'progress-snapshot.json', 'damage_model/standalone.py', 'damage_model/_owned_host.py',
                 'tools/collect_continuous.py', 'tools/collect_parallel.py', 'catalogs/game-0.111.0.raw.json',
                 'configs/real-runs-8s.json'):
        path = tmp_path/name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'fixture')
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (tmp_path/'release.json').write_text(json.dumps(dict(schema='standalone-collector-release/v1', productionReady=False, files=files)))
    return tmp_path


def test_corrupted_module_rejected_before_launch(bundle):
    assert release.verify(bundle)
    (bundle/'damage_model/standalone.py').write_text('changed')
    with pytest.raises(ValueError, match='Release file changed'):
        release.verify(bundle)


def test_required_unpinned_module_is_rejected(bundle):
    path = bundle/'release.json'
    manifest = json.loads(path.read_text())
    del manifest['files']['damage_model/_owned_host.py']
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match='Required release file'):
        release.verify(bundle)


def test_symlink_to_external_code_is_rejected(bundle, tmp_path):
    outside = tmp_path.parent/(tmp_path.name+'-outside.py')
    outside.write_bytes(b'fixture')
    path = bundle/'damage_model/standalone.py'
    path.unlink()
    path.symlink_to(outside)
    with pytest.raises(ValueError, match='Release file changed'):
        release.verify(bundle)


def test_launch_pins_module_search_and_catalog(bundle, monkeypatch):
    monkeypatch.setattr(sys, 'argv', ['release_tool.py','run','--bundle',str(bundle),'--module','tools.collect_parallel',
                                    '--','--teacher',str(bundle/'teacher.json'),'--config',str(bundle/'configs/real-runs-8s.json')])
    launched = []
    monkeypatch.setattr(release.os, 'execve', lambda *args: launched.append(args))
    release.main()
    _, command, env = launched[0]
    assert '-P' in command and env['PYTHONSAFEPATH'] == '1'
    assert env['PYTHONPATH'] == str(bundle)
    assert command[command.index('--catalog')+1] == str(bundle/'catalogs/game-0.111.0.raw.json')


@pytest.mark.parametrize('flag', ['--teacher', '--config'])
def test_foreign_policy_path_rejected(bundle, monkeypatch, flag):
    args = ['release_tool.py','run','--bundle',str(bundle),'--module','tools.collect_parallel',
            '--','--teacher',str(bundle/'teacher.json'),'--config',str(bundle/'configs/real-runs-8s.json')]
    args[args.index(flag)+1] = '/foreign/policy.json'
    monkeypatch.setattr(sys, 'argv', args)
    monkeypatch.setattr(release.os, 'execve', lambda *args: pytest.fail('Must not launch'))
    with pytest.raises(ValueError, match='explicit frozen'):
        release.main()
