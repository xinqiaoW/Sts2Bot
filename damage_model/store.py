from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import time
import uuid
from collections import Counter
from .schema import Build, canonical, digest
from .observation import validate_hp


class Store:
    def __init__(self, path):
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript('''
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS builds(id TEXT PRIMARY KEY,family TEXT,split TEXT,body TEXT);
            CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,build_id TEXT,target TEXT,seed TEXT,
                teacher TEXT,status TEXT DEFAULT 'pending',lease TEXT,lease_until REAL,attempts INTEGER DEFAULT 0,
                result TEXT,created REAL,FOREIGN KEY(build_id) REFERENCES builds(id));
            CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,job_id TEXT,lease TEXT,status TEXT,result TEXT,finished REAL);
            CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created);
            CREATE INDEX IF NOT EXISTS attempts_recent ON attempts(finished,status,job_id);
            CREATE INDEX IF NOT EXISTS attempts_job ON attempts(job_id);
            CREATE TABLE IF NOT EXISTS collection_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS target_origins(
                build_id TEXT,run_hash TEXT,origin_floor INTEGER,target_floor INTEGER,target_id TEXT,
                PRIMARY KEY(build_id,run_hash,origin_floor,target_floor,target_id));
            CREATE TABLE IF NOT EXISTS job_scope_changes(
                id INTEGER PRIMARY KEY,job_id TEXT,previous_status TEXT,new_status TEXT,reason TEXT,changed_at REAL);
            CREATE TABLE IF NOT EXISTS job_quarantines(
                job_id TEXT PRIMARY KEY,reason TEXT NOT NULL,evidence TEXT NOT NULL,
                original_job TEXT NOT NULL,attempts_sha256 TEXT NOT NULL,quarantined_at REAL NOT NULL);
        ''')

    def add_build(self, build):
        encoded = canonical(build.to_dict())
        self._begin_write('add_build')
        with self.db:
            self.db.execute('INSERT OR IGNORE INTO builds VALUES(?,?,?,?)',
                            (build.id, build.family, build.split, encoded))
        return Build.from_dict(json.loads(self.db.execute('SELECT body FROM builds WHERE id=?', (build.id,)).fetchone()[0]))

    def schedule(self, build, targets, seeds, teacher, *, reactivate_excluded=False):
        build = self.add_build(build)
        teacher_json = canonical(teacher)
        existing = self.db.execute('SELECT DISTINCT teacher FROM jobs').fetchall()
        if any(row[0] != teacher_json for row in existing):
            raise ValueError('Use a separate database for a different teacher configuration')
        added = 0
        self._begin_write('schedule')
        with self.db:
            for target in targets:
                for seed in seeds:
                    job_id = digest([build.id, target['id'], str(seed), teacher])
                    added += self.db.execute('INSERT OR IGNORE INTO jobs(id,build_id,target,seed,teacher,created) VALUES(?,?,?,?,?,?)',
                        (job_id, build.id, canonical(target), str(seed), teacher_json, time.time())).rowcount
                    if reactivate_excluded:
                        restored = self.db.execute("UPDATE jobs SET status='pending' WHERE id=? AND status='excluded_target'", (job_id,)).rowcount
                        if restored:
                            self.db.execute('INSERT INTO job_scope_changes(job_id,previous_status,new_status,reason,changed_at) VALUES(?,?,?,?,?)',
                                (job_id, 'excluded_target', 'pending', 'New recorded source window', time.time()))
                        added += restored
        return added

    def _begin_write(self, operation):
        # Retry only a BUSY BEGIN before this connection owns a transaction.
        # Never replay statements or commits: their effects may be ambiguous.
        for attempt in range(3):
            try:
                self.db.execute('BEGIN IMMEDIATE')
                break
            except sqlite3.OperationalError as error:
                code = getattr(error, 'sqlite_errorcode', None)
                if (not isinstance(code, int) or code & 0xff != sqlite3.SQLITE_BUSY
                        or self.db.in_transaction or attempt == 2):
                    raise
                print(json.dumps({'event': operation + '_busy', 'retry': attempt + 1,
                                  'sqlite_errorcode': code}), flush=True)
                time.sleep(0.25 * 2 ** attempt)

    def claim(self, seconds=180):
        self._begin_write('claim')
        try:
            # Persist expired attempts before returning their jobs to the queue.
            self.db.execute("""INSERT INTO attempts(job_id,lease,status,result,finished)
                SELECT id,lease,'expired','{"status":"LeaseExpired"}',? FROM jobs
                WHERE status='running' AND lease_until < ?""", (time.time(), time.time()))
            self.db.execute("UPDATE jobs SET status='pending',lease=NULL WHERE status='running' AND lease_until < ?", (time.time(),))
            row = self.db.execute("SELECT * FROM jobs WHERE status='pending' ORDER BY created LIMIT 1").fetchone()
            if row is None:
                self.db.commit()
                return None
            lease = uuid.uuid4().hex
            self.db.execute("UPDATE jobs SET status='running',lease=?,lease_until=?,attempts=attempts+1 WHERE id=?",
                            (lease, time.time() + seconds, row['id']))
            build = json.loads(self.db.execute('SELECT body FROM builds WHERE id=?', (row['build_id'],)).fetchone()[0])
            self.db.commit()
            return {**dict(row), 'lease': lease, 'build': build, 'target': json.loads(row['target']), 'teacher': json.loads(row['teacher'])}
        except BaseException:
            self.db.rollback()
            raise

    def finish(self, job, result):
        observation = result.get('trainingObservation')
        complete = result.get('status') == 'Passed' and result.get('combatEnded') is True and observation and observation.get('complete') is True
        if complete:
            required = ('initialHp','initialMaxHp','finalHp','finalMaxHp','netHpLoss','playerDied','initialBuild')
            if any(k not in observation for k in required): raise ValueError('Incomplete observation')
            validate_hp(observation, job['target'])
            requested = Build.from_dict(job['build'])
            actual = observation['initialBuild']
            if actual.get('character') != 'SILENT' or actual.get('ascension') != 10 or actual.get('actId') != requested.act_id:
                raise ValueError('Actual environment differs from requested build')
            if any(type(c.get('upgradeLevel')) is not int
                   or type(c.get('enchantmentAmount', 0)) is not int
                   or (c.get('enchantmentId') is not None and type(c['enchantmentId']) is not str)
                   for c in actual['cards']):
                raise ValueError('Invalid actual card state fields')
            if Counter((c['id'],c['upgradeLevel'],c.get('enchantmentId') or '',c.get('enchantmentAmount',0)) for c in actual['cards']) != Counter((c.id,c.upgrade,c.enchantment_id,c.enchantment_amount) for c in requested.cards):
                raise ValueError('Actual starting deck differs from requested build')
            if [r['id'] for r in actual['relics']] != [r.id for r in requested.relics]:
                raise ValueError('Actual relic order/inventory differs from requested build')
            for live, planned in zip(actual['relics'],requested.relics):
                if canonical(live.get('counters',{})) != canonical(dict(planned.state)):
                    raise ValueError('Actual relic counters differ from requested build')
        status = 'complete' if complete else 'failed'
        encoded = canonical(result)
        self._begin_write('finish')
        with self.db:
            updated = self.db.execute("UPDATE jobs SET status=?,result=? WHERE id=? AND lease=? AND status='running'",
                         (status, encoded, job['id'], job['lease'])).rowcount
            if updated != 1: raise ValueError('Stale or already submitted lease')
            self.db.execute('INSERT INTO attempts(job_id,lease,status,result,finished) VALUES(?,?,?,?,?)',
                            (job['id'],job['lease'],status,encoded,time.time()))
        return status

    def retry_startup(self, job, result, max_attempts=3):
        """Retry identified native runtime failures, retaining every attempt (legacy name)."""
        if result.get('status') not in ('NativeStartupCacheFailure','NativeEnumCacheFailure','NativeWinePageFault','NativeMenuCleanupFailure','NativeFinalizerCleanupFailure','NativeFinalizerReuseFailure','NativeAssetLoadingFailure'):
            raise ValueError('Not a retryable native runtime failure')
        self._begin_write('retry_startup')
        try:
            row=self.db.execute("SELECT attempts FROM jobs WHERE id=? AND lease=? AND status='running'",
                                (job['id'],job['lease'])).fetchone()
            if row is None: raise ValueError('Stale retry lease')
            if row[0]>=max_attempts:
                self.db.rollback()
                return self.finish(job,result)
            self.db.execute("UPDATE jobs SET status='pending',lease=NULL,lease_until=NULL,result=? WHERE id=?",
                            (canonical(result),job['id']))
            self.db.execute('INSERT INTO attempts(job_id,lease,status,result,finished) VALUES(?,?,?,?,?)',
                            (job['id'],job['lease'],'retry',canonical(result),time.time()))
            self.db.commit()
            return 'retry'
        except BaseException:
            self.db.rollback()
            raise

    def retry_or_quarantine_native(self, job, result, *, max_attempts, reason, evidence):
        """Commit an attempt and retry/isolate atomically; peers never see a transient failed job."""
        from .resilience import NATIVE_FAILURES, cleanup_deadline_failure
        if (result.get('status') not in NATIVE_FAILURES
                or ((result.get('trainingObservation') or {}).get('complete') is True
                    and not cleanup_deadline_failure(result))):
            raise ValueError('Only incomplete native failures or diagnosed cleanup timeouts can use autonomous isolation')
        if type(max_attempts) is not int or not 2 <= max_attempts <= 3:
            raise ValueError('Native retries must have a bounded total of two or three attempts')
        if not reason or not evidence or not Path(evidence).is_file():
            raise ValueError('Persist diagnostic evidence before retrying or isolating')
        self._begin_write('retry_or_quarantine_native')
        try:
            row = self.db.execute("SELECT * FROM jobs WHERE id=? AND lease=? AND status='running'",
                                  (job['id'], job['lease'])).fetchone()
            if row is None:
                raise ValueError('Stale native failure lease')
            attempts = [dict(a) for a in self.db.execute(
                'SELECT * FROM attempts WHERE job_id=? ORDER BY id', (job['id'],))]
            if len(attempts) != row['attempts'] - 1:
                raise ValueError('Native failure has incomplete attempt evidence')
            terminal = row['attempts'] >= max_attempts
            encoded = canonical(result)
            self.db.execute('INSERT INTO attempts(job_id,lease,status,result,finished) VALUES(?,?,?,?,?)',
                            (job['id'], job['lease'], 'failed' if terminal else 'retry', encoded, time.time()))
            if not terminal:
                self.db.execute("UPDATE jobs SET status='pending',lease=NULL,lease_until=NULL,result=? WHERE id=?",
                                (encoded, job['id']))
                status = 'retry'
            else:
                original = {**dict(row), 'status': 'failed', 'result': encoded}
                attempts = [dict(a) for a in self.db.execute(
                    'SELECT * FROM attempts WHERE job_id=? ORDER BY id', (job['id'],))]
                self.db.execute('INSERT INTO job_quarantines VALUES(?,?,?,?,?,?)',
                    (job['id'], reason, evidence, canonical(original), digest(attempts), time.time()))
                self.db.execute("UPDATE jobs SET status='quarantined',result=? WHERE id=?", (encoded, job['id']))
                status = 'quarantined'
            self.db.commit()
            return status
        except BaseException:
            self.db.rollback()
            raise

    def quarantine_failed(self, job_id, *, expected_attempts, reason, evidence):
        """Explicitly isolate a diagnosed failure without rewriting its result or attempts."""
        if type(expected_attempts) is not int or expected_attempts < 1:
            raise ValueError('Expected a positive attempt count')
        if not isinstance(reason, str) or not reason.strip() or not isinstance(evidence, str) or not evidence.strip():
            raise ValueError('Quarantine requires a diagnosis and evidence reference')
        self._begin_write('quarantine_failed')
        try:
            row = self.db.execute('SELECT * FROM jobs WHERE id=?', (job_id,)).fetchone()
            if row is None or row['status'] != 'failed' or row['attempts'] != expected_attempts:
                raise ValueError('Only the diagnosed failed job at the expected attempt count can be quarantined')
            attempts = [dict(a) for a in self.db.execute(
                'SELECT * FROM attempts WHERE job_id=? ORDER BY id', (job_id,))]
            if len(attempts) != expected_attempts or not attempts or attempts[-1]['status'] != 'failed' or attempts[-1]['result'] != row['result']:
                raise ValueError('Failed job has incomplete or inconsistent attempt evidence')
            record = dict(job_id=job_id, reason=reason, evidence=evidence,
                          original_job=canonical(dict(row)), attempts_sha256=digest(attempts),
                          quarantined_at=time.time())
            self.db.execute('INSERT INTO job_quarantines VALUES(:job_id,:reason,:evidence,:original_job,:attempts_sha256,:quarantined_at)', record)
            self.db.execute("UPDATE jobs SET status='quarantined' WHERE id=?", (job_id,))
            self.db.commit()
            return record
        except BaseException:
            self.db.rollback()
            raise

    def rows(self):
        from .run_import import source_groups
        families = source_groups(self.db)
        for row in self.db.execute("SELECT jobs.*,builds.body,builds.split FROM jobs JOIN builds ON build_id=builds.id WHERE status='complete'"):
            result = {**dict(row), 'build': json.loads(row['body']), 'target': json.loads(row['target']),
                      'teacher': json.loads(row['teacher']), 'result': json.loads(row['result'])}
            if row['build_id'] in families:
                result['build']['family'] = families[row['build_id']]
                result['split'] = Build.from_dict(result['build']).split
            yield result

    # Historical aggregation for the retired synthetic parent-selection loop.
    # Disabled 2026-09-10: collection, training and the viewer use other paths.
    # Retained as comments at the user's request; see docs/历史垃圾箱/code-cleanup-20260910.md.
    # def summaries(self):
    #     from collections import defaultdict
    #     groups = defaultdict(list)
    #     for row in self.rows(): groups[(row['build_id'],row['target']['id'])].append(row['result']['trainingObservation'])
    #     out = defaultdict(dict)
    #     for (build_id, target), rows in groups.items():
    #         values = [r['netHpLoss'] for r in rows]
    #         n, mean = len(values), sum(values) / len(values)
    #         variance = sum((v - mean)**2 for v in values) / (n - 1) if n > 1 else None
    #         out[build_id][target] = {'n':n,'mean':mean,'variance':variance,'death_rate':sum(r['playerDied'] for r in rows)/n}
    #     return dict(out)

    def counts(self):
        return dict(self.db.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status').fetchall())
