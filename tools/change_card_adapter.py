"""Separate protocol-3 inputs from protocol-2 labels, preserving immutable history."""
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3
import time

from damage_model.schema import canonical, digest
from damage_model.store import Store


def migrate_card_adapter(source, destination, teacher):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    temporary = destination.with_suffix('.preparing.sqlite')
    if source == destination or destination.exists() or temporary.exists():
        raise ValueError('A new destination without an earlier preparation is required')
    destination.parent.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)) as old:
        old.row_factory=sqlite3.Row
        old.execute('BEGIN')
        counts=dict(old.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
        if counts.get('running'):
            raise ValueError('Drain the source before changing the input adapter')
        teachers=[json.loads(r[0]) for r in old.execute('SELECT DISTINCT teacher FROM jobs')]
        if len(teachers)!=1 or teachers[0].get('collector_protocol')!=2 or teacher.get('collector_protocol')!=3:
            raise ValueError('Only the explicit protocol 2 to 3 migration is supported')
        adapter={'collector_protocol','collector_source','collector_sha256'}
        if {k:v for k,v in teachers[0].items() if k not in adapter}!={k:v for k,v in teacher.items() if k not in adapter}:
            raise ValueError('The game and search teacher must remain unchanged')
        if teachers[0]['collector_sha256']==teacher['collector_sha256']:
            raise ValueError('Protocol 3 requires the new native observer')
        pending=list(old.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY created,id"))
        with closing(sqlite3.connect(temporary)) as snapshot:
            old.backup(snapshot)
        new=Store(temporary)
        try:
            db=new.db
            with db:
                # Native logs/results/attempts and quarantine originals stay in source.
                for row in old.execute("SELECT * FROM jobs WHERE status IN ('complete','quarantined','failed')"):
                    db.execute('INSERT OR IGNORE INTO prior_collected_inputs VALUES(?,?,?,?,?,?,?,?)',
                               (row['build_id'],json.loads(row['target'])['id'],row['seed'],str(source),row['id'],
                                row['status'],row['teacher'],hashlib.sha256((row['result'] or '').encode()).hexdigest()))
                for table in ('attempts','job_quarantines','job_scope_changes','jobs'):
                    db.execute('DELETE FROM '+table)
                if db.execute("SELECT 1 FROM sqlite_master WHERE name='teacher_batch_origins'").fetchone():
                    db.execute('ALTER TABLE teacher_batch_origins RENAME TO prior_teacher_batch_origins_protocol2')
                db.execute('''CREATE TABLE teacher_batch_origins(
                    job_id TEXT PRIMARY KEY,source_database TEXT NOT NULL,source_job_id TEXT NOT NULL,
                    source_status TEXT NOT NULL,source_attempts INTEGER NOT NULL,migrated_at REAL NOT NULL)''')
                for row in pending:
                    target=json.loads(row['target'])
                    jid=digest([row['build_id'],target['id'],row['seed'],teacher])
                    db.execute('INSERT INTO jobs(id,build_id,target,seed,teacher,created) VALUES(?,?,?,?,?,?)',
                               (jid,row['build_id'],row['target'],row['seed'],canonical(teacher),row['created']))
                    db.execute('INSERT INTO teacher_batch_origins VALUES(?,?,?,?,?,?)',
                               (jid,str(source),row['id'],row['status'],row['attempts'],time.time()))
                report={'source_database':str(source),'destination_database':str(destination),'before_counts':counts,
                        'migrated_pending':len(pending),'old_teacher':teachers[0],'new_teacher':teacher,
                        'completed_results_relabelled':0,'created_at':time.time(),
                        'policy':'saved_card_state_v3',
                        'prior_inputs':db.execute('SELECT count(*) FROM prior_collected_inputs').fetchone()[0]}
                db.execute('INSERT OR REPLACE INTO collection_settings VALUES(?,?)',('card_adapter_migration',canonical(report)))
            assert new.counts()==({'pending':len(pending)} if pending else {})
            assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
            db.execute('VACUUM')
            db.execute('PRAGMA wal_checkpoint(TRUNCATE)')
            db.execute('PRAGMA journal_mode=DELETE')
        finally:new.db.close()
    temporary.replace(destination)
    return report
