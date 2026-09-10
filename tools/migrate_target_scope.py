"""Preview, or migrate a drained queue, preserving results and source histories."""
import argparse
from contextlib import ExitStack
import hashlib
import json
from pathlib import Path
import sqlite3

from damage_model.catalog import Catalog
from damage_model.provenance import teacher_for
from damage_model.schema import canonical
from damage_model.store import Store
from damage_model.target_scope import plan_window, migrate_window


def preserved_hashes(db):
    queries = {
        'complete_jobs': "SELECT * FROM jobs WHERE status='complete' ORDER BY id",
        'job_inputs_and_attempt_counts': 'SELECT id,build_id,target,seed,teacher,attempts,result,created FROM jobs ORDER BY id',
        'attempts': 'SELECT * FROM attempts ORDER BY id',
        'builds': 'SELECT * FROM builds ORDER BY id',
        'sources': 'SELECT * FROM source_runs ORDER BY hash',
        'origins': 'SELECT * FROM build_origins ORDER BY build_id,run_hash,floor',
        'source_import_history': 'SELECT * FROM source_import_history ORDER BY hash,version',
    }
    values = {}
    for name, query in queries.items():
        h = hashlib.sha256()
        for row in db.execute(query):
            h.update((canonical(list(row))+'\n').encode())
        values[name] = h.hexdigest()
    return values


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--db', required=True)
    p.add_argument('--config', default='configs/real-runs.json')
    p.add_argument('--output', required=True)
    p.add_argument('--apply', action='store_true')
    p.add_argument('--session', default='data/rental-session.json')
    args = p.parse_args()
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    database = Path(args.db).resolve()
    catalog = Catalog.load('catalogs/game-0.111.0.raw.json', args.config)
    if not args.apply:
        with sqlite3.connect(f'file:{database.as_posix()}?mode=ro', uri=True) as db:
            db.row_factory = sqlite3.Row
            db.execute('BEGIN')
            report = plan_window(db, catalog)['report']
    else:
        import fcntl
        session = json.loads(Path(args.session).read_text())
        if Path(session['active_db']).resolve() != database:
            raise ValueError('Session/database mismatch')
        with ExitStack() as stack:
            paths = [database.with_suffix('.pool.lock'), database.with_suffix('.continuous.lock')]
            paths += [Path(json.loads(Path(r).read_text())['data_dir'])/'collector.lock' for r in session['runtimes']]
            for path in paths:
                lock = stack.enter_context(path.open('a+'))
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            store = Store(database)
            try:
                before = preserved_hashes(store.db)
                # A complete SQLite backup, never a copy of the live main file.
                backup = Path(args.output).with_suffix('.before.sqlite')
                if backup.exists():
                    raise ValueError('Migration backup already exists; inspect earlier evidence before retrying')
                with sqlite3.connect(backup) as saved:
                    store.db.backup(saved)
                    assert saved.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
                report = migrate_window(store, catalog, teacher_for(catalog, 'configs/teacher.json'))
                after = preserved_hashes(store.db)
                if report['added']:
                    # New jobs can change only this hash; all prior job fields are
                    # checked against the retained pre-migration database below.
                    before_compare = {k:v for k,v in before.items() if k != 'job_inputs_and_attempt_counts'}
                    after_compare = {k:v for k,v in after.items() if k != 'job_inputs_and_attempt_counts'}
                else:
                    before_compare, after_compare = before, after
                assert before_compare == after_compare
                store.db.execute('ATTACH DATABASE ? AS before_scope', (str(backup),))
                assert store.db.execute('''SELECT count(*) FROM (
                    SELECT id,build_id,target,seed,teacher,attempts,result,created FROM before_scope.jobs
                    EXCEPT SELECT id,build_id,target,seed,teacher,attempts,result,created FROM main.jobs)''').fetchone()[0] == 0
                store.db.execute('DETACH DATABASE before_scope')
                report.update(preserved_before=before, preserved_after=after,
                              previous_jobs_preserved=True, backup=str(backup))
            finally:
                store.db.close()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    main()
