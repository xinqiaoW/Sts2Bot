import json
from pathlib import Path
import signal
import shutil
import sqlite3
import subprocess
import sys
import time

import pytest

from damage_model.store import Store


@pytest.mark.parametrize('preparation_finished', [True, False])
def test_serial_backups_finish_and_stop_cleanly(tmp_path, preparation_finished):
    if shutil.disk_usage(tmp_path).free < 20 * 1024**3:
        pytest.skip('Backup integration test requires the production 20 GiB reserve')
    run = tmp_path/'run'
    (run/'queues').mkdir(parents=True)
    databases = [run/'queues'/f'{name}.backfill.sqlite' for name in ('real', 'mutation', 'targeted')]
    for db in databases:
        Store(db).db.close()
    if preparation_finished:
        (run/'prepare-report.json').write_text(json.dumps({'apply': True, 'sources': [{'output': str(p)} for p in databases]}))
    (run/'queues/backfill-manifest.json').write_text(json.dumps({'version': 1, 'seed_indices': [4, 24],
        'sources': ['/source/'+name+'.sqlite' for name in ('real', 'mutation', 'targeted')]}))
    for name in ('deployment.json', 'runtimes.json'):
        (run/name).write_text('{}')
    command = [sys.executable, '-m', 'tools.one_off.backfill_backup', '--run-dir', str(run),
               '--directory', str(tmp_path/'backups'), '--initial-delay', '0']
    with (tmp_path/'backup.log').open('wb') as log:
        process = subprocess.Popen(command, stdout=log, stderr=log)
        try:
            deadline = time.monotonic()+30
            while not (run/'targeted.backfill.backup.json').exists():
                assert process.poll() is None
                assert time.monotonic() < deadline
                time.sleep(.05)
            process.send_signal(signal.SIGTERM)
            assert process.wait(timeout=5) == 0
        finally:
            if process.poll() is None:
                process.kill()
                process.wait()
    for db in databases:
        state = json.loads((run/(db.stem+'.backup.json')).read_text())
        assert state['state'] == 'saved'
        with sqlite3.connect(Path(state['directory'])/db.name) as snapshot:
            assert snapshot.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
