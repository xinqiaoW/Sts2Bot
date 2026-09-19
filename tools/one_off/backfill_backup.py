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
    args = parser.parse_args()
    if args.interval < 300 or args.initial_delay < 0:
        raise ValueError('Invalid backup timing')
    root, destination = Path(args.run_dir).resolve(), Path(args.directory).resolve()
    report = json.loads((root/'prepare-report.json').read_text())
    databases = [Path(source['output']) for source in report['sources']]
    if not report['apply'] or not databases or any(not p.is_file() for p in databases):
        raise ValueError('Prepared backfill databases are required')
    destination.mkdir(parents=True, exist_ok=True)
    for name in ('deployment.json', 'prepare-report.json', 'runtimes.json'):
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
            for db in databases:
                if stopping:
                    break
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
