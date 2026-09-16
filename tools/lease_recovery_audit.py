"""Recognize only explicitly diagnosed expired leases; never modify collection data."""
import hashlib
import json
from pathlib import Path


def verify_registered_reclaim(row, database, root):
    root = Path(root).resolve()
    registry = root / 'data/diagnosed-lease-recoveries.json'
    if not registry.exists():
        return False
    value = json.loads(registry.read_text())
    assert value['schema'] == 1
    matches = [entry for entry in value['attempts']
               if entry['database'] == database and entry['attempt_id'] == row['id']]
    if not matches:
        return False
    assert len(matches) == 1, 'Duplicate recovery evidence'
    entry = matches[0]
    assert row['status'] == 'expired' and json.loads(row['result']) == {'status': 'LeaseExpired'}
    assert all(row[key] == entry[key] for key in ('job_id', 'lease', 'finished'))
    evidence = (root / entry['evidence']).resolve()
    assert evidence.is_relative_to(root / 'evidence')

    def checked(name):
        path = (evidence / name).resolve()
        assert path.is_relative_to(evidence)
        data = path.read_bytes()
        assert hashlib.sha256(data).hexdigest() == entry['files'][name], name
        return data

    preflight = json.loads(checked('preflight.json'))
    launch = json.loads(checked('services-started.json'))
    assert entry['files'] and entry['worker_logs']
    for name in entry['files']:
        checked(name)
    for name in entry['worker_logs']:
        text = checked(name).decode()
        assert 'sqlite3.OperationalError: database is locked' in text
        assert "self._begin_write('finish')" in text
    assert preflight['time'] < launch['time'] <= row['finished']
    state = preflight['databases'][database]
    assert state['write_lock_available'] and not state['counts'].get('failed', 0)
    originals = [job for job in state['expired_running']
                 if job['id'] == row['job_id'] and job['lease'] == row['lease']]
    assert len(originals) == 1
    original = originals[0]
    assert original['status'] == 'running' and original['lease_until'] < preflight['time']
    assert original['result'] is None
    assert preflight['runtimes'] and all(r['lock_available'] for r in preflight['runtimes'].values())
    return True
