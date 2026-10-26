"""Durable per-runtime receipt; recover only while its collector lock is held.

SQLite remains authoritative. Never rerun combat or overwrite a newer lease to
recover a result. A receipt survives a write failure or a process interruption.
"""
import json
import os
from pathlib import Path
import time
import uuid

from .schema import canonical


def path_for(directory):
    return Path(directory) / 'pending-submission.json'


def _sync_directory(directory):
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _save(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x') as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _sync_directory(path.parent)


def record_claim(directory, job):
    path = path_for(directory)
    if path.exists():
        raise RuntimeError('Unresolved result receipt: ' + str(path))
    _save(path, dict(schema='collector-result-outbox/v1', job=job, action='claimed'))


def submit(store, directory, job, result, action='finish', *, wait_for_lock=False, **options):
    path = path_for(directory)
    previous = json.loads(path.read_text())
    if previous['action'] != 'claimed' or previous['job'] != job:
        raise ValueError('Result receipt does not own this exact claim')
    _save(path, dict(schema=previous['schema'], job=job, action=action,
                     result=result, options=options))
    return (recover_waiting if wait_for_lock else recover)(store, directory)


def recover_waiting(store, directory):
    """Wait for a rejected BEGIN; archive proven expired results without writing them."""
    from .store import LeaseNotOwned, WriteBusyBeforeBegin
    while True:
        try:
            return recover(store, directory, archive_expired=True)
        except WriteBusyBeforeBegin as error:
            print(json.dumps({'event': 'waiting_for_result_lock',
                              'sqlite_errorcode': error.sqlite_errorcode}), flush=True)
            time.sleep(1)
        except LeaseNotOwned:
            # A peer can expire/reassign the lease while BEGIN waits, then
            # release the writer lock before the bounded BEGIN retry succeeds.
            # The rejected transaction rolled back. Re-read authoritative
            # attempts/ownership; only the existing proven-expiry path archives.
            print(json.dumps({'event': 'rechecking_result_lease'}), flush=True)


def _archive_expired(path, job):
    # Keep the original receipt bytes on the same filesystem. The expired
    # attempt remains authoritative; a late result must never become a label.
    archive = path.parent / 'expired-results'
    archive.mkdir(exist_ok=True)
    _sync_directory(path.parent)
    destination = archive / (job['lease'] + '-' + uuid.uuid4().hex + '.json')
    os.replace(path, destination)
    _sync_directory(archive)
    _sync_directory(path.parent)
    print(json.dumps(dict(event='expired_result_archived', job=job['id'],
                          lease=job['lease'], evidence=str(destination))), flush=True)
    return 'superseded_expired'


def recover(store, directory, *, archive_expired=False):
    """Caller must hold the runtime collector lock; pool recovery also holds pool locks."""
    path = path_for(directory)
    if not path.exists():
        return None
    receipt = json.loads(path.read_text())
    if receipt['schema'] != 'collector-result-outbox/v1':
        raise ValueError('Unknown result receipt schema')
    job, action = receipt['job'], receipt['action']
    owner = store.owner(job) if hasattr(store, 'owner') else store
    row = owner.db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone()
    if row is None or row['build_id'] != job['build_id'] or row['teacher'] != canonical(job['teacher']):
        raise ValueError('Receipt belongs to a different queue or teacher')
    attempts = list(owner.db.execute('SELECT status,result FROM attempts WHERE job_id=? AND lease=?',
                                    (job['id'], job['lease'])))
    if len(attempts) > 1:
        raise ValueError('Multiple attempts for one receipt lease')
    if attempts:
        status, encoded = attempts[0]
        value = json.loads(encoded)
        if action == 'claimed':
            if status not in ('interrupted', 'expired'):
                raise ValueError('Claim-only receipt unexpectedly has a submitted result')
            status = 'recovered_pending'
        else:
            result = receipt['result']
            if (archive_expired and status == 'expired'
                    and value == {'status': 'LeaseExpired'}
                    and row['lease'] != job['lease']
                    and action in ('finish', 'retry_startup', 'retry_or_quarantine_native')):
                return _archive_expired(path, job)
            if value != result and not (action == 'finish' and value.get('status') == 'InvalidObservation'
                                        and value.get('native_result') == result):
                raise ValueError('Existing attempt differs from durable result; retain for review')
            if status == 'failed' and action == 'retry_or_quarantine_native':
                status = 'quarantined'
    elif row['status'] != 'running' or row['lease'] != job['lease']:
        raise ValueError('Stale receipt; refusing to overwrite newer work')
    elif action == 'claimed':
        owner.abandon_claim(job, evidence=str(path))
        status = 'recovered_pending'
    elif action == 'finish':
        from .store import LeaseNotOwned
        try:
            status = owner.finish(job, receipt['result'])
        except LeaseNotOwned:
            raise
        except ValueError as error:
            status = owner.finish(job, dict(status='InvalidObservation', error=str(error),
                                           native_result=receipt['result']))
    elif action in ('retry_startup', 'retry_or_quarantine_native'):
        status = getattr(owner, action)(job, receipt['result'], **receipt['options'])
    else:
        raise ValueError('Unknown result receipt action')
    # A crash after commit but before this removal is handled by the exact-attempt
    # comparison above; no second attempt or new combat is created.
    path.unlink()
    _sync_directory(path.parent)
    return status
