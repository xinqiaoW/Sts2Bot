import fcntl
import importlib.util
import json
from pathlib import Path
import sys

import pytest

source = Path(__file__).resolve().parents[1] / 'experiments/standalone-simulator'
sys.path.insert(0, str(source))
spec = importlib.util.spec_from_file_location('replay_build_panel_owned', source / 'replay_build_panel.py')
panel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(panel)
sys.path.remove(str(source))


@pytest.mark.parametrize('fails', [False, True])
def test_final_auditor_cannot_take_controller_lock_during_replay(tmp_path, monkeypatch, fails):
    campaign = tmp_path / 'source'
    campaign.mkdir()
    setup = {'runtimes': [str(tmp_path / 'original-runtime.json')]}
    (campaign / 'setup.json').write_text(json.dumps(setup))
    output = tmp_path / 'replay'
    argv = ['replay_build_panel.py']
    for name in ('source-root', 'campaign', 'host-dll', 'runtime-template', 'progress-snapshot'):
        argv.extend(['--' + name, str(campaign)])
    argv.extend(['--output', str(output)])
    monkeypatch.setattr(sys, 'argv', argv)

    def running(args):
        assert json.loads((output / 'setup.json').read_text()) == setup
        with (output / 'batch.lock').open('r') as lock:
            with pytest.raises(BlockingIOError):
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if fails:
            raise RuntimeError('retained replay failure')

    monkeypatch.setattr(panel, 'replay_panel', running)
    if fails:
        with pytest.raises(RuntimeError, match='retained replay failure'):
            panel.main()
    else:
        panel.main()
    with (output / 'batch.lock').open('r') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    with pytest.raises(FileExistsError):
        panel.main()
