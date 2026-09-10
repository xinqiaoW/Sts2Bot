"""Keep two consistent local backup slots without touching the active collection."""
import argparse
import fcntl
import json
from pathlib import Path
import shutil
import time

from tools.rental_backup import atomic_json, snapshot


def source_metadata(db):
    """Capture replay positions before the DB snapshot, never ahead of its rows."""
    captured = {}
    for name in ('data/collection-session.json', 'data/active-collection.json',
                 str(Path(db).with_suffix('.continuous.progress.json')),
                 'data/external/spire-codex/cursor.json', 'configs/teacher.json', 'configs/real-runs.json'):
        path = Path(name)
        if path.is_file():
            captured[Path(path.name)] = path.read_bytes()
    session = json.loads(captured.get(Path('collection-session.json'), b'{}'))
    if session.get('config'):
        path = Path(session['config'])
        captured[Path(path.name)] = path.read_bytes()
    if session.get('mutation_policy'):
        path = Path(session['mutation_policy'])
        captured[Path(path.name)] = path.read_bytes()
    if session.get('backfill_dir'):
        directory = Path(session['backfill_dir'])
        # Read the plan before phase cursors: restoring an earlier plan simply
        # replays a completed phase, and imports/jobs are idempotent.
        paths = [directory / name for name in ('plan.json', 'export-rate.json', 'latest.json')]
        paths += sorted(directory.glob('*/cursor.json'))
        for path in paths:
            if path.is_file():
                captured[Path('source-backfill') / path.relative_to(directory)] = path.read_bytes()
    return captured


def backup_once(db, directory, state_path):
    directory, state_path = Path(directory), Path(state_path)
    previous = json.loads(state_path.read_text()) if state_path.exists() else {}
    last = previous if previous.get('state') == 'saved' else previous.get('last_success', {})
    slot = 'slot-b' if last.get('slot') == 'slot-a' else 'slot-a'
    target = directory / slot
    metadata = source_metadata(db)
    manifest = snapshot(db, target)
    for relative, content in metadata.items():
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
    state = {'state': 'saved', 'updated': time.time(), 'slot': slot,
             'directory': str(target.resolve()), 'manifest': manifest}
    atomic_json(state_path, state)
    return state


def record_failure(state_path, error):
    path = Path(state_path)
    previous = json.loads(path.read_text()) if path.exists() else {}
    last = previous if previous.get('state') == 'saved' else previous.get('last_success')
    atomic_json(path, {'state': 'failed', 'updated': time.time(), 'error': str(error), 'last_success': last})


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='data/collection-real-runs-v2.sqlite')
    parser.add_argument('--directory', default='backups/01-active')
    parser.add_argument('--state', default='data/local-backup.json')
    parser.add_argument('--interval', type=int, default=300)
    parser.add_argument('--once', action='store_true')
    args = parser.parse_args()
    if args.interval < 60:
        raise ValueError('Backup interval must be at least 60 seconds')
    if not Path(args.db).is_file():
        raise FileNotFoundError(args.db)
    Path(args.state).parent.mkdir(parents=True, exist_ok=True)
    with Path(args.state).with_suffix('.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        while True:
            try:
                if shutil.disk_usage(Path(args.db).parent).free < 20 * 1024**3:
                    raise RuntimeError('Less than 20 GiB free; keep the previous backup intact')
                state = backup_once(args.db, args.directory, args.state)
                print(json.dumps(state), flush=True)
                if args.once:
                    return
            except Exception as error:
                record_failure(args.state, error)
                print(json.dumps({'backup_error': str(error)}), flush=True)
                if args.once:
                    raise
            time.sleep(args.interval)


if __name__ == '__main__':
    main()
