"""Durable per-runtime receipt; recover only while its collector lock is held.

SQLite remains authoritative. Never rerun combat or overwrite a newer lease to
recover a result. A receipt survives a write failure or a process interruption.
"""
import json
import os
from pathlib import Path
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


def submit(store, directory, job, result, action='finish', **options):
    path = path_for(directory)
    previous = json.loads(path.read_text())
    if previous['action'] != 'claimed' or previous['job'] != job:
        raise ValueError('Result receipt does not own this exact claim')
    _save(path, dict(schema=previous['schema'], job=job, action=action,
                     result=result, options=options))
    return recover(store, directory)


def recover(store, directory):
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
        try:
            status = owner.finish(job, receipt['result'])
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
