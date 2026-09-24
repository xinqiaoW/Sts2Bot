import json
import sys
import time

import pytest

from damage_model.standalone import StandaloneProcess


def host(tmp_path, body):
    script = tmp_path / 'host.py'
    script.write_text('import json, sys, time, os\nrequest = json.load(open(sys.argv[-1]))\n' + body)
    return StandaloneProcess(tmp_path, tmp_path / 'data', script, sys.executable)


def request():
    return {'runId': 'a' * 32, 'timeoutSeconds': 1}


COMPLETION = "print(json.dumps({'status': 'StandaloneCompleted', 'runId': request['runId'], 'collectionRequest': request}), flush=True)\n"


def test_completion_uses_only_this_process_output(tmp_path):
    process = host(tmp_path, COMPLETION)
    process.log_path.write_text('{"status":"StandaloneCompleted","runId":"stale"}\n')
    result = process.run(request())
    assert result['status'] == 'StandaloneCompleted'
    assert result['runId'] == request()['runId']
    assert process.process is None
    assert process.log is None


@pytest.mark.parametrize('body,status', [
    ('pass\n', 'StandaloneInvalidResult'),
    (COMPLETION + COMPLETION, 'StandaloneInvalidResult'),
    ("request['runId'] = 'b' * 32\n" + COMPLETION, 'StandaloneInvalidResult'),
    ("request['unexpected'] = True\n" + COMPLETION, 'StandaloneInvalidResult'),
    (COMPLETION + 'sys.exit(7)\n', 'StandaloneFailed'),
    ('print("{malformed")\n', 'StandaloneInvalidResult'),
])
def test_invalid_or_crashed_host_cannot_complete(tmp_path, body, status):
    process = host(tmp_path, body)
    result = process.run(request())
    assert result['status'] == status
    assert result['combatEnded'] is False
    assert result['provenance']['backend'] == 'standalone-managed-native'
    assert process.process is None


def test_deadline_stops_owned_host(tmp_path):
    process = host(tmp_path, 'print(os.getpid(), flush=True)\ntime.sleep(30)\n')
    started = time.monotonic()
    result = process.run(request())
    assert result['status'] == 'StandaloneTimeout'
    assert time.monotonic() - started < 5
    import os
    with pytest.raises(ProcessLookupError):
        os.kill(int(process.log_path.read_text().strip()), 0)


def test_spawn_failure_is_a_recordable_failure(tmp_path):
    process = host(tmp_path, COMPLETION)
    process.dotnet = str(tmp_path / 'missing-runtime')
    assert process.run(request())['status'] == 'StandaloneFailed'
    assert process.log is None


def test_standalone_failure_retries_then_quarantines_with_logs(tmp_path):
    from damage_model.resilience import preserve_failure
    from damage_model.schema import Build, Card, Relic
    from damage_model.store import Store
    store = Store(tmp_path / 'queue.sqlite')
    build = Build('OVERGROWTH', 1, (Card('DEFEND_SILENT'),), (Relic('RING_OF_THE_SNAKE'),), (), 'test')
    teacher = {'execution_backend': 'standalone-managed-native', 'validation_scope': 'isolated-experiment'}
    store.schedule(build, [{'id': 'TEST'}], ['seed'], teacher)
    process = host(tmp_path, 'print("diagnostic", flush=True)\nsys.exit(4)\n')
    for i in range(3):
        job = store.claim()
        offset = process.log_path.stat().st_size if process.log_path.exists() else 0
        req = {'runId': format(i + 1, '032x'), 'timeoutSeconds': 1}
        result = process.run(req)
        evidence, reason = preserve_failure(process, job, result, offset, tmp_path / 'evidence')
        from pathlib import Path
        manifest = json.loads(Path(evidence).read_text())
        assert manifest['diagnosis']['backend'] == 'standalone-managed-native'
        assert (Path(evidence).parent / 'standalone.log').read_text() == 'diagnostic\n'
        assert store.retry_or_quarantine_native(job, result, max_attempts=3, reason=reason, evidence=evidence) == ('retry' if i < 2 else 'quarantined')
    assert store.db.execute('SELECT count(*) FROM attempts').fetchone()[0] == 3
    assert store.db.execute('SELECT count(*) FROM job_quarantines').fetchone()[0] == 1
    assert store.counts().get('complete', 0) == 0
    assert store.claim() is None


def test_ambient_jit_override_cannot_change_validated_policy(tmp_path, monkeypatch):
    monkeypatch.setenv('DOTNET_TieredCompilation', '1')
    monkeypatch.setenv('COMPlus_TieredCompilation', '1')
    process = host(tmp_path, COMPLETION)
    assert process.env['DOTNET_TieredCompilation'] == '0'
    assert 'COMPlus_TieredCompilation' not in process.env


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux worker ownership contract')
def test_hard_worker_death_terminates_host(tmp_path):
    import os
    from pathlib import Path
    import signal
    import subprocess

    script = tmp_path / 'sleeping_host.py'
    pid_path = tmp_path / 'host.pid'
    script.write_text('import os, pathlib, time\n'
                      f'pathlib.Path({str(pid_path)!r}).write_text(str(os.getpid()))\n'
                      'time.sleep(60)\n')
    code = ('from damage_model.standalone import StandaloneProcess\n'
            f'p = StandaloneProcess({str(tmp_path)!r}, {str(tmp_path / "data")!r}, '
            f'{str(script)!r}, {sys.executable!r})\n'
            f'p.run({dict(runId="f" * 32, timeoutSeconds=60)!r})\n')
    worker = subprocess.Popen([sys.executable, '-c', code],
                              cwd=Path(__file__).resolve().parents[1])
    host_pid = None
    def host_alive():
        try:
            return Path(f'/proc/{host_pid}/stat').read_text().rsplit(')', 1)[1].split()[0] != 'Z'
        except FileNotFoundError:
            return False
    try:
        deadline = time.monotonic() + 10
        while not pid_path.exists() and time.monotonic() < deadline:
            assert worker.poll() is None
            time.sleep(0.02)
        assert pid_path.exists()
        host_pid = int(pid_path.read_text())
        assert host_alive()
        worker.kill()
        worker.wait(timeout=5)
        deadline = time.monotonic() + 5
        while host_alive() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not host_alive(), 'Managed host survived the loss of its worker'
    finally:
        if worker.poll() is None:
            worker.kill()
        worker.wait(timeout=5)
        if host_pid is not None and host_alive():
            os.killpg(host_pid, signal.SIGKILL)


def test_launcher_rejects_already_lost_parent(tmp_path):
    from pathlib import Path
    import subprocess
    import damage_model.standalone
    marker = tmp_path / 'unexpected-start'
    launcher = Path(damage_model.standalone.__file__).with_name('_owned_host.py')
    result = subprocess.run([sys.executable, str(launcher), '-1', sys.executable,
                             '-c', f'open({str(marker)!r}, "w").close()'], timeout=5)
    assert result.returncode == 125
    assert not marker.exists()
