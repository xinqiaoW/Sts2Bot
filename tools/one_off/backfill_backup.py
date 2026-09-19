"""Serialize snapshots of the one-off seed backfill without changing collectors."""
import argparse
import fcntl
import json
from pathlib import Path
import shutil
import signal
import time

from tools.local_backup import backup_once, record_failure


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True)
    parser.add_argument('--directory', required=True)
    parser.add_argument('--interval', type=int, default=3600)
    parser.add_argument('--initial-delay', type=int, default=300)
    parser.add_argument('--additional-db', action='append', default=[],
                        help='Also snapshot an active normal-collection database in the same serial loop')
    args = parser.parse_args()
    if args.interval < 300 or args.initial_delay < 0:
        raise ValueError('Invalid backup timing')
    root, destination = Path(args.run_dir).resolve(), Path(args.directory).resolve()
    report_path = root/'prepare-report.json'
    if report_path.exists():
        report = json.loads(report_path.read_text())
        if not report['apply']:
            raise ValueError('An applied backfill is required')
        databases = [Path(source['output']) for source in report['sources']]
    else:
        # The manifest is written only after all historical inputs validate.
        # Collection can consume committed tasks while the same preparer adds
        # the remaining queues. Snapshot each queue once it exists.
        manifest = json.loads((root/'queues/backfill-manifest.json').read_text())
        if manifest.get('version') != 1 or manifest.get('seed_indices') != [4, 24]:
            raise ValueError('A validated backfill manifest is required')
        databases = [root/'queues'/(Path(source).stem+'.backfill.sqlite') for source in manifest['sources']]
    additional = [Path(p).resolve(strict=True) for p in args.additional_db]
    databases.extend(additional)
    if len({p.stem for p in databases}) != len(databases):
        raise ValueError('Backup database names must be unique')
    if not databases or not any(p.is_file() for p in databases):
        raise ValueError('At least one prepared backfill queue is required')
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('deployment.json', 'runtimes.json'):
        shutil.copy2(root/name, destination/name)
    shutil.copy2(root/'queues/backfill-manifest.json', destination/'backfill-manifest.json')
    stopping = False

    def request_stop(signum, frame):
        nonlocal stopping
        stopping = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, request_stop)

    def pause(seconds):
        deadline = time.monotonic() + seconds
        while not stopping and time.monotonic() < deadline:
            time.sleep(min(1, max(0, deadline-time.monotonic())))

    with (root/'backup-loop.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pause(args.initial_delay)
        while not stopping:
            if report_path.exists():
                shutil.copy2(report_path, destination/report_path.name)
            for db in databases:
                if stopping:
                    break
                if not db.is_file():
                    print(json.dumps({'database': str(db), 'state': 'waiting_for_queue'}), flush=True)
                    continue
                state = root/(db.stem+'.backup.json')
                try:
                    if shutil.disk_usage(destination).free < 20 * 1024**3:
                        raise RuntimeError('Less than 20 GiB free; preserve previous backups')
                    saved = backup_once(db, destination/db.stem, state)
                    print(json.dumps({'database': str(db), **saved}), flush=True)
                except Exception as error:
                    record_failure(state, error)
                    print(json.dumps({'database': str(db), 'backup_error': str(error)}), flush=True)
            pause(args.interval)


if __name__ == '__main__':
    main()
