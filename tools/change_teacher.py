"""Create a separate teacher batch from uncollected jobs; never relabel outcomes."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

from damage_model.schema import canonical, digest


def migrate_pending(source, destination, teacher):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination or destination.exists():
        raise ValueError('A new, separate destination is required')
    temporary = destination.with_suffix('.preparing.sqlite')
    if temporary.exists():
        raise ValueError('An earlier preparation exists; inspect it before retrying')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as old:
        old.row_factory = sqlite3.Row
        old.execute('BEGIN')
        before = dict(old.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
        if before.get('running', 0):
            raise ValueError('Drain all source jobs before changing teacher')
        teachers = [json.loads(r[0]) for r in old.execute('SELECT DISTINCT teacher FROM jobs')]
        if len(teachers) != 1 or teachers[0] == teacher:
            raise ValueError('Expected exactly one different source teacher')
        if {k: v for k, v in teachers[0].items() if k != 'search_ms'} != {
                k: v for k, v in teacher.items() if k != 'search_ms'}:
            raise ValueError('This migration changes only the short-search time budget')
        if not isinstance(teacher['search_ms'], int) or teacher['search_ms'] <= teachers[0]['search_ms']:
            raise ValueError('Expected a larger short-search budget')
        rows = list(old.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY created,id"))
        for row in rows:
            if not old.execute('SELECT 1 FROM target_origins WHERE build_id=? AND target_id=?',
                               (row['build_id'], json.loads(row['target'])['id'])).fetchone():
                raise ValueError('Pending job has no recorded source target')
        with closing(sqlite3.connect(temporary)) as new:
            old.backup(new)
            new.execute('PRAGMA journal_mode=DELETE')
            stamp = time.time()
            with new:
                # Historical evidence remains in the immutable source database.
                new.execute('DELETE FROM attempts')
                new.execute('DELETE FROM job_scope_changes')
                new.execute('DELETE FROM jobs')
                new.execute('''CREATE TABLE teacher_batch_origins(
                    job_id TEXT PRIMARY KEY,source_database TEXT NOT NULL,
                    source_job_id TEXT NOT NULL,source_status TEXT NOT NULL,
                    source_attempts INTEGER NOT NULL,migrated_at REAL NOT NULL)''')
                for row in rows:
                    jid = digest([row['build_id'], json.loads(row['target'])['id'], row['seed'], teacher])
                    new.execute('''INSERT INTO jobs(id,build_id,target,seed,teacher,created)
                                   VALUES(?,?,?,?,?,?)''',
                                (jid,row['build_id'],row['target'],row['seed'],canonical(teacher),row['created']))
                    new.execute('INSERT INTO teacher_batch_origins VALUES(?,?,?,?,?,?)',
                                (jid,str(source),row['id'],row['status'],row['attempts'],stamp))
                report = {'source_database':str(source),'destination_database':str(destination),
                          'before_counts':before,'migrated_pending':len(rows),'created_at':stamp,
                          'old_teacher':teachers[0],'new_teacher':teacher,
                          'preserved_failed_in_source':before.get('failed',0),
                          'completed_results_relabelled':0}
                new.execute('INSERT OR REPLACE INTO collection_settings VALUES(?,?)',
                            ('teacher_batch_migration',canonical(report)))
            if new.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                raise ValueError('New batch failed SQLite integrity check')
            assert new.execute('SELECT count(*) FROM jobs').fetchone()[0] == len(rows)
            assert new.execute('SELECT count(*) FROM attempts').fetchone()[0] == 0
            new.execute('VACUUM')
    temporary.replace(destination)
    return report
