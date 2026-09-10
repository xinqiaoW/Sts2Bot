"""Periodically send a consistent SQLite backup through the task's SSH tunnel."""
import argparse
from contextlib import closing, contextmanager
import fcntl
import hashlib
import json
import mmap
from pathlib import Path
import shutil
import sqlite3
import subprocess
import time


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False))
    temporary.replace(path)


@contextmanager
def cached_snapshot_pages(path):
    """Keep a read-only mapping during verification of the completed copy."""
    with Path(path).open('rb') as stream, mmap.mmap(stream.fileno(), 0, access=mmap.ACCESS_READ) as pages:
        # Touch one byte per OS page so fragmented SQLite overflow pages do not
        # repeatedly fault from disk during quick_check. The copy is immutable
        # here, and the mapping is released before promotion to the saved slot.
        for offset in range(0, len(pages), mmap.PAGESIZE):
            _ = pages[offset]
        yield


def snapshot(db_path, directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / Path(db_path).name
    temporary = target.with_suffix(target.suffix + '.tmp')
    with closing(sqlite3.connect(f'file:{Path(db_path).resolve()}?mode=ro', uri=True, timeout=30)) as source:
        if source.execute('PRAGMA journal_mode').fetchone()[0].lower() == 'wal':
            # Pin one WAL read snapshot: concurrent collectors can keep writing,
            # without restarting every incremental backup step from page one.
            source.execute('BEGIN')
            source.execute('SELECT count(*) FROM sqlite_schema').fetchone()
        with closing(sqlite3.connect(temporary)) as destination:
            source.backup(destination, pages=1024, sleep=.05)
            destination.execute('PRAGMA journal_mode=DELETE')
            with cached_snapshot_pages(temporary):
                if destination.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise ValueError('Backup did not pass SQLite integrity check')
                counts = dict(destination.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
    temporary.replace(target)
    checksum = hashlib.sha256()
    with target.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''): checksum.update(block)
    manifest = {'created': time.time(), 'database': target.name, 'bytes': target.stat().st_size,
                'sha256': checksum.hexdigest(), 'counts': counts}
    atomic_json(directory / 'manifest.json', manifest)
    return manifest


def upload(args):
    started = time.time()
    directory = Path('data/rental-backup-upload') / Path(args.db).stem
    manifest = snapshot(args.db, directory)
    for path in ('data/rental-session.json', 'data/active-collection.json',
                 str(Path(args.db).with_suffix('.continuous.progress.json')),
                 'configs/teacher.json', 'configs/v1.json', 'configs/real-runs.json',
                 'data/external/spire-codex/cursor.json'):
        source = Path(path)
        if source.exists(): shutil.copy2(source, directory / source.name)
    result = subprocess.run(['rsync', '-ar', '--stats', '--backup', '--suffix=.previous', '--delay-updates',
        '-e', 'ssh -p 22001 -i /root/.ssh/sts2_transfer -o IdentitiesOnly=yes -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=15 -o ServerAliveCountMax=3',
        str(directory) + '/', 'pl@127.0.0.1:backups/rental-20260906/'],
        capture_output=True, text=True, timeout=240)
    if result.returncode:
        raise RuntimeError(f'Backup transfer failed ({result.returncode}): {result.stderr[-2000:]}')
    status = {'state': 'uploaded', 'updated': time.time(), 'seconds': time.time() - started,
              'destination': '01:Sts2Bot/backups/rental-20260906/', 'manifest': manifest,
              'rsync_stats': result.stdout[-2000:]}
    atomic_json('data/rental-backup.json', status)
    print(json.dumps(status), flush=True)
    return manifest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='data/collection-real-runs-v2.sqlite')
    parser.add_argument('--stop-at', type=float, help='Optional UTC Unix deadline; omit to back up until stopped')
    parser.add_argument('--interval', type=int, default=300)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if args.interval < 60: raise ValueError('Backup interval must be at least 60 seconds')
    with Path('data/rental-backup.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                manifest = upload(args)
                if args.once: return
                if args.stop_at is not None and time.time() >= args.stop_at and not manifest['counts'].get('running', 0):
                    state = json.loads(Path('data/rental-backup.json').read_text())
                    state['final'] = True
                    atomic_json('data/rental-backup.json', state)
                    return
            except Exception as error:
                atomic_json('data/rental-backup.json', {'state': 'failed', 'updated': time.time(), 'error': str(error)})
                print(json.dumps({'backup_error': str(error)}), flush=True)
                if args.once: raise
            if args.stop_at is not None and time.time() > args.stop_at + 600:
                raise RuntimeError('Final backup did not complete within ten minutes after deadline')
            if args.stop_at is None:
                time.sleep(args.interval)
            else:
                remaining = args.stop_at - time.time()
                time.sleep(min(args.interval, max(5, remaining)) if remaining > 0 else 15)


if __name__ == '__main__': main()
