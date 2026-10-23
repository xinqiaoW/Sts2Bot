"""Read-only, incrementally indexed browser for the active collection queues.

Only the disposable viewer cache is writable. Never instantiate Store on a source
database: doing so can migrate it or acquire a writer lock.
"""
from __future__ import annotations

from collections import Counter
from contextlib import closing, nullcontext
from datetime import datetime, timezone
import argparse
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import sqlite3
import threading
import time
from urllib.parse import parse_qs, urlsplit

from damage_model.observation import validate_hp, validate_cards
from damage_model.provenance import completed_by_expected_backend
from damage_model.schema import Build

ROOT = Path(__file__).resolve().parents[1]
DATASETS = {'real': '真实构筑', 'mutations': '普通变异', 'targeted': '专项变异'}
FIELDS = ('trainingObservation', 'status', 'combatEnded', 'elapsedMilliseconds',
          'finishedTurn', 'collector', 'provenance', 'productionReady',
          'productionLabels', 'collectionRequest', 'runId')


def read_db(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=3)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('PRAGMA cache_size=-4096')
    db.execute('PRAGMA mmap_size=134217728')
    return db


def loads(value, default=None):
    return json.loads(value) if value else default


def utc(value):
    return datetime.fromtimestamp(value, timezone.utc).isoformat() if value else None


class CollectionView:
    def __init__(self, directory, cache, localization=None):
        self.directory, self.cache = Path(directory).resolve(), Path(cache).resolve()
        self.cache.parent.mkdir(parents=True, exist_ok=True)
        self.stop = threading.Event()
        self.loc = loads(Path(localization).read_text()) if localization else {}
        with closing(sqlite3.connect(self.cache)) as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS sources(dataset TEXT PRIMARY KEY,path TEXT,
                    identity TEXT,job_cursor INTEGER DEFAULT 0,attempt_cursor INTEGER DEFAULT 0,
                    attempt_max INTEGER DEFAULT 0,updated REAL,counts TEXT,error TEXT);
                CREATE TABLE IF NOT EXISTS builds(dataset TEXT,id TEXT,body TEXT,act TEXT,
                    split TEXT,card_count INTEGER,relic_count INTEGER,search TEXT,
                    PRIMARY KEY(dataset,id));
                CREATE TABLE IF NOT EXISTS planned(dataset TEXT,job_id TEXT,build_id TEXT,
                    target_id TEXT,target_name TEXT,kind TEXT,seed TEXT,
                    PRIMARY KEY(dataset,job_id));
                CREATE INDEX IF NOT EXISTS planned_pair ON planned(dataset,build_id,target_id);
                CREATE TABLE IF NOT EXISTS battles(dataset TEXT,job_id TEXT,build_id TEXT,
                    target_id TEXT,seed TEXT,initial_hp INTEGER,max_hp INTEGER,final_hp INTEGER,
                    final_max_hp INTEGER,loss INTEGER,died INTEGER,turns INTEGER,elapsed REAL,
                    finished REAL,backend TEXT,scope TEXT,flags TEXT,worker TEXT,
                    PRIMARY KEY(dataset,job_id));
                CREATE INDEX IF NOT EXISTS battle_pair ON battles(dataset,build_id,target_id);
                CREATE INDEX IF NOT EXISTS battle_finished ON battles(finished DESC);
                CREATE INDEX IF NOT EXISTS battle_loss ON battles(loss);
                CREATE TABLE IF NOT EXISTS issues(dataset TEXT,job_id TEXT,build_id TEXT,
                    target_id TEXT,status TEXT,attempts INTEGER,error TEXT,
                    PRIMARY KEY(dataset,job_id));
                CREATE INDEX IF NOT EXISTS viewer_build_dims
                    ON builds(dataset,id,act,split,card_count,relic_count,search);
                CREATE INDEX IF NOT EXISTS viewer_job_dims
                    ON planned(dataset,job_id,target_id,target_name,kind);
            ''')
        self.paths = {n: self.directory / 'db' / (n + '.sqlite') for n in DATASETS}
        self.bodies = {}
        self.build_cursors = {}
        self.metadata_at = 0

    def name(self, group, key):
        suffix = '.name' if group == 'monsters' else '.title'
        return self.loc.get(group, {}).get(key + suffix, key)

    def build_info(self, body):
        result = dict(body)
        result['act_name'] = self.name('acts', body['act_id'])
        result['card_count'] = len(body['cards'])
        cards = Counter(json.dumps(c, sort_keys=True) for c in body['cards'])
        result['card_items'] = [{**loads(c), 'name': self.name('cards', loads(c)['id']),
                                 'count': n, 'enchantment_name': self.name(
                                     'enchantments', loads(c).get('enchantment_id', ''))}
                                for c, n in cards.items()]
        result['relic_items'] = [{**r, 'name': self.name('relics', r['id'])}
                                 for r in body['relics']]
        return result

    def refresh_metadata(self, writer):
        pending_metadata = False
        for dataset, path in self.paths.items():
            try:
                with closing(read_db(path)) as src:
                    identity = f'{path.stat().st_dev}:{path.stat().st_ino}'
                    maximum = src.execute('SELECT COALESCE(MAX(id),0) FROM attempts').fetchone()[0]
                    old = writer.execute('SELECT * FROM sources WHERE dataset=?', (dataset,)).fetchone()
                    if old and (old['identity'] != identity or old['attempt_cursor'] > maximum):
                        for table in ('builds', 'planned', 'battles', 'issues', 'sources'):
                            writer.execute(f'DELETE FROM {table} WHERE dataset=?', (dataset,))
                        old = None
                        self.build_cursors[dataset] = 0
                    writer.execute('INSERT OR IGNORE INTO sources(dataset,path,identity) VALUES(?,?,?)',
                                   (dataset, str(path), identity))
                    counts = dict(src.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status'))
                    writer.execute('UPDATE sources SET counts=?,attempt_max=?,updated=?,error=NULL WHERE dataset=?',
                                   (json.dumps(counts), maximum, time.time(), dataset))
                    for row in src.execute('SELECT rowid,* FROM builds WHERE rowid>? ORDER BY rowid',
                                           (self.build_cursors.get(dataset, 0),)):
                        body = loads(row['body']); self.bodies[dataset, row['id']] = body
                        info = self.build_info(body)
                        search = ' '.join([row['id'], self.name('acts', body['act_id']),
                            *[c['id'] + ' ' + c['name'] for c in info['card_items']],
                            *[r['id'] + ' ' + r['name'] for r in info['relic_items']]])
                        writer.execute('INSERT OR IGNORE INTO builds VALUES(?,?,?,?,?,?,?,?)',
                            (dataset, row['id'], row['body'], body['act_id'], row['split'],
                             len(body['cards']), len(body['relics']), search))
                        self.build_cursors[dataset] = row['rowid']
                    cursor = writer.execute('SELECT job_cursor FROM sources WHERE dataset=?', (dataset,)).fetchone()[0]
                    while not self.stop.is_set():
                        rows = src.execute('SELECT rowid,id,build_id,target,seed FROM jobs WHERE rowid>? ORDER BY rowid LIMIT 2000', (cursor,)).fetchall()
                        if not rows: break
                        for row in rows:
                            target = loads(row['target'])
                            writer.execute('INSERT OR IGNORE INTO planned VALUES(?,?,?,?,?,?,?)',
                                (dataset, row['id'], row['build_id'], target['id'],
                                 self.name('encounters', target['id']), target['room_type'], row['seed']))
                        cursor = rows[-1]['rowid']
                        writer.execute('UPDATE sources SET job_cursor=? WHERE dataset=?', (cursor, dataset))
                        writer.commit()
                        pending_metadata = pending_metadata or len(rows) == 2000
                        break  # Fairness: expose all three queues before full backfill.
                    writer.execute("DELETE FROM issues WHERE dataset=? AND status IN ('quarantined','failed')", (dataset,))
                    for row in src.execute("SELECT id,build_id,target,status,attempts,json_extract(result,'$.error') AS error FROM jobs WHERE status IN ('quarantined','failed')"):
                        writer.execute('INSERT OR REPLACE INTO issues VALUES(?,?,?,?,?,?,?)',
                            (dataset, row['id'], row['build_id'], loads(row['target'])['id'],
                             row['status'], row['attempts'], row['error'] or '无错误说明'))
                    writer.commit()
            except (OSError, sqlite3.Error, ValueError, KeyError) as error:
                logging.exception('Viewer metadata: %s', dataset)
                writer.execute('INSERT OR IGNORE INTO sources(dataset,path) VALUES(?,?)', (dataset, str(path)))
                writer.execute('UPDATE sources SET error=? WHERE dataset=?', (str(error), dataset))
                writer.commit()
        self.metadata_at = time.time() - (25 if pending_metadata else 0)

    def sync_chunk(self, writer, dataset, limit=200):
        source = writer.execute('SELECT * FROM sources WHERE dataset=?', (dataset,)).fetchone()
        if not source or source['error']: return False
        extracts = ','.join("'$." + f + "'" for f in FIELDS)
        with closing(read_db(self.paths[dataset])) as src:
            rows = src.execute(f'''SELECT a.id,a.job_id,a.status,a.finished,j.build_id,j.target,j.seed,j.teacher,
                CASE WHEN a.status='complete' AND json_valid(a.result)
                     THEN json_extract(a.result,{extracts}) END AS compact
                FROM attempts a LEFT JOIN jobs j ON j.id=a.job_id
                WHERE a.id>? AND a.id<=? ORDER BY a.id LIMIT ?''',
                (source['attempt_cursor'], source['attempt_max'], limit)).fetchall()
        for row in rows:
            if row['status'] != 'complete': continue
            try:
                result = dict(zip(FIELDS, loads(row['compact'])))
                target, teacher = loads(row['target']), loads(row['teacher'])
                obs = result.get('trainingObservation') or {}
                flags = []
                try:
                    if not (result['combatEnded'] and obs.get('complete') and
                            completed_by_expected_backend({'teacher': teacher, 'seed': row['seed'], 'target': target}, result)):
                        flags.append('终局状态或后端身份不一致')
                    validate_hp(obs, target)
                    validate_cards(obs.get('initialBuild', {}).get('cards', []),
                                   Build.from_dict(self.bodies[dataset, row['build_id']]).cards,
                                   teacher.get('collector_protocol', 2))
                except (ValueError, KeyError, TypeError) as error:
                    flags.append(str(error))
                def integer(key):
                    value = obs.get(key)
                    return value if type(value) is int else None
                collector = result.get('collector') or {}
                writer.execute('INSERT OR REPLACE INTO battles VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                    (dataset, row['job_id'], row['build_id'], target['id'], row['seed'],
                     integer('initialHp'), integer('initialMaxHp'), integer('finalHp'), integer('finalMaxHp'),
                     integer('netHpLoss'), int(obs['playerDied']) if type(obs.get('playerDied')) is bool else None,
                     result.get('finishedTurn'), (result['elapsedMilliseconds'] / 1000)
                     if isinstance(result.get('elapsedMilliseconds'), (int, float)) else None,
                     row['finished'], teacher.get('execution_backend', 'native-wine'),
                     teacher.get('validation_scope', 'native-collection'), json.dumps(flags, ensure_ascii=False),
                     collector.get('worker', '')))
                writer.execute("DELETE FROM issues WHERE dataset=? AND job_id=? AND status='index_error'",
                               (dataset, row['job_id']))
            except (ValueError, KeyError, TypeError) as error:
                writer.execute('DELETE FROM battles WHERE dataset=? AND job_id=?', (dataset, row['job_id']))
                writer.execute('INSERT OR REPLACE INTO issues VALUES(?,?,?,?,?,?,?)',
                    (dataset, row['job_id'], row['build_id'], '', 'index_error', 0, str(error)))
                logging.warning('Cannot index %s / %s: %s', dataset, row['job_id'], error)
        if rows:
            writer.execute('UPDATE sources SET attempt_cursor=? WHERE dataset=?', (rows[-1]['id'], dataset))
            writer.commit()
        return len(rows) == limit

    def run(self):
        with closing(sqlite3.connect(self.cache, timeout=10)) as writer:
            writer.row_factory = sqlite3.Row
            writer.execute('PRAGMA synchronous=NORMAL')
            writer.execute('PRAGMA cache_size=-8192')
            while not self.stop.is_set():
                try:
                    if time.time() - self.metadata_at > 30: self.refresh_metadata(writer)
                    more = False
                    for dataset in DATASETS:
                        more = self.sync_chunk(writer, dataset) or more
                    self.stop.wait(.08 if more else 5)
                except Exception:
                    writer.rollback()
                    logging.exception('Viewer index refresh failed')
                    self.stop.wait(10)

    def state(self, snapshot=None):
        with (nullcontext(snapshot) if snapshot is not None else closing(read_db(self.cache))) as db:
            if snapshot is None: db.execute('BEGIN')
            sources = []
            for row in db.execute('SELECT * FROM sources'):
                s = dict(row); s['counts'] = loads(s['counts'], {})
                s['label'] = DATASETS[s['dataset']]
                s['indexed'] = db.execute('SELECT COUNT(*) FROM battles WHERE dataset=?', (s['dataset'],)).fetchone()[0]
                s['planned'] = db.execute('SELECT COUNT(*) FROM planned WHERE dataset=?', (s['dataset'],)).fetchone()[0]
                sources.append(s)
        session_path = self.directory / 'data/collection-session.json'
        session = loads(session_path.read_text(), {}) if session_path.exists() else {}
        heartbeat_path = self.directory / 'db/real.parallel.json'
        heartbeat = loads(heartbeat_path.read_text(), {}) if heartbeat_path.exists() else {}
        return {'sources': sources, 'workers': session.get('workers'),
                'collection_state': heartbeat.get('state', 'unknown'),
                'heartbeat_at': utc(heartbeat.get('updated')), 'now': utc(time.time()),
                'scope': session.get('teacher', {}).get('validation_scope'),
                'backend': session.get('execution_backend'), 'directory': str(self.directory)}

    def filters(self, query):
        clauses, args = ['1=1'], []
        for key, column, choices in [('dataset', 'b.dataset', set(DATASETS)),
                ('act', 'u.act', None), ('kind', 'p.kind', {'Monster', 'Elite', 'Boss'}),
                ('target', 'b.target_id', None), ('split', 'u.split', {'train', 'validation', 'test'})]:
            value = query.get(key, '')
            if not value or value == 'all': continue
            if len(value) > 128 or (choices and value not in choices): raise ValueError('无效筛选条件：' + key)
            clauses.append(column + '=?'); args.append(value)
        if query.get('q'):
            clauses.append('u.search LIKE ?'); args.append('%' + query['q'][:160] + '%')
        return ' AND '.join(clauses), args

    @staticmethod
    def join():
        # Newly built caches have no ANALYZE statistics. Keep battles first:
        # otherwise SQLite can scan every build against all tasks in its dataset.
        return '''FROM battles b
            CROSS JOIN builds u INDEXED BY viewer_build_dims ON u.dataset=b.dataset AND u.id=b.build_id
            CROSS JOIN planned p INDEXED BY viewer_job_dims ON p.dataset=b.dataset AND p.job_id=b.job_id'''

    def overview(self, query):
        where, args = self.filters(query); join = self.join()
        with closing(read_db(self.cache)) as db:
            db.execute('BEGIN')
            summary = dict(db.execute(f'''SELECT COUNT(*) AS battles,COUNT(DISTINCT b.build_id) AS builds,
                COUNT(DISTINCT b.target_id) AS targets,AVG(loss) AS mean_loss,MIN(loss) AS min_loss,
                MAX(loss) AS max_loss,SUM(died) AS deaths,SUM(loss=0) AS zero_loss,
                AVG(turns) AS mean_turns,AVG(elapsed) AS mean_elapsed,
                SUM(flags!='[]') AS flagged,COUNT(loss) AS metric_samples {join} WHERE {where}''', args).fetchone())
            histogram = [dict(r) for r in db.execute(f'SELECT loss,COUNT(*) AS n {join} WHERE {where} GROUP BY loss ORDER BY loss', args)]
            targets = [dict(r) for r in db.execute(f'''SELECT b.target_id,p.target_name,p.kind,u.act,
                COUNT(*) AS n,COUNT(DISTINCT b.build_id) AS builds,AVG(loss) AS mean_loss,
                SUM(died) AS deaths,AVG(turns) AS mean_turns {join} WHERE {where}
                GROUP BY b.target_id,p.target_name,p.kind,u.act ORDER BY mean_loss DESC,n DESC''', args)]
            coverage = [dict(r) for r in db.execute(f'''SELECT n,COUNT(*) AS pairs FROM
                (SELECT COUNT(*) AS n {join} WHERE {where} GROUP BY b.dataset,b.build_id,b.target_id)
                GROUP BY n ORDER BY n''', args)]
            splits = [dict(r) for r in db.execute(f'SELECT u.split,COUNT(*) AS n {join} WHERE {where} GROUP BY u.split', args)]
            acts = [{'id': r[0], 'name': self.name('acts', r[0])} for r in db.execute('SELECT DISTINCT act FROM builds ORDER BY act')]
            state = self.state(db)
        losses = []
        for row in histogram:
            if row['loss'] is not None: losses.extend([row['loss']] * row['n'])
        summary['median_loss'] = ((losses[(len(losses)-1)//2] + losses[len(losses)//2]) / 2) if losses else None
        return {'summary': summary, 'histogram': histogram, 'targets': targets,
                'coverage': coverage, 'splits': splits, 'acts': acts, 'state': state}

    def battles(self, query):
        where, args = self.filters(query)
        for key, op in [('loss_min', '>='), ('loss_max', '<=')]:
            if query.get(key, '') != '':
                value = int(query[key])
                if not -1000 <= value <= 1000: raise ValueError('掉血筛选超出范围')
                where += f' AND b.loss{op}?'; args.append(value)
        if query.get('outcome') in ('dead', 'alive'):
            where += ' AND b.died=?'; args.append(int(query['outcome'] == 'dead'))
        if query.get('outcome') == 'flagged': where += " AND b.flags!='[]'"
        order = {'recent': 'b.finished DESC,b.job_id', 'loss_desc': 'b.loss DESC,b.job_id',
                 'loss_asc': 'b.loss,b.job_id'}.get(query.get('sort', 'recent'))
        if not order: raise ValueError('无效排序')
        page = max(1, min(100000, int(query.get('page', 1))))
        with closing(read_db(self.cache)) as db:
            db.execute('BEGIN')
            total = db.execute(f'SELECT COUNT(*) {self.join()} WHERE {where}', args).fetchone()[0]
            rows = [dict(r) for r in db.execute(f'''SELECT b.*,p.target_name,p.kind,u.act,u.card_count,
                u.relic_count,u.split {self.join()} WHERE {where} ORDER BY {order} LIMIT 40 OFFSET ?''',
                [*args, (page-1)*40])]
        for r in rows: r['flags'] = loads(r['flags'], [])
        return {'rows': rows, 'total': total, 'page': page, 'page_size': 40}

    def detail(self, query):
        dataset, build_id = query.get('dataset'), query.get('build')
        if dataset not in DATASETS or not build_id: raise ValueError('请选择构筑')
        with closing(read_db(self.cache)) as db:
            db.execute('BEGIN')
            row = db.execute('SELECT * FROM builds WHERE dataset=? AND id=?', (dataset, build_id)).fetchone()
            if not row: raise ValueError('找不到构筑')
            build = self.build_info(loads(row['body'])); build.update(id=build_id, split=row['split'])
            targets = [dict(r) for r in db.execute('''SELECT p.target_id,p.target_name,p.kind,COUNT(*) AS planned,
                COUNT(b.job_id) AS n,AVG(b.loss) AS mean_loss,SUM(b.died) AS deaths,
                MIN(b.loss) AS min_loss,MAX(b.loss) AS max_loss
                FROM planned p LEFT JOIN battles b ON b.dataset=p.dataset AND b.job_id=p.job_id
                WHERE p.dataset=? AND p.build_id=? GROUP BY p.target_id,p.target_name,p.kind ORDER BY n DESC,p.target_name''',
                (dataset, build_id))]
            target_id = query.get('target') or (targets[0]['target_id'] if targets else '')
            seeds = [dict(r) for r in db.execute('''SELECT p.seed,p.job_id,b.initial_hp,b.max_hp,b.final_hp,
                b.final_max_hp,b.loss,b.died,b.turns,b.elapsed,b.finished,b.flags,b.backend,b.scope
                FROM planned p LEFT JOIN battles b ON b.dataset=p.dataset AND b.job_id=p.job_id
                WHERE p.dataset=? AND p.build_id=? AND p.target_id=? ORDER BY p.seed''',
                (dataset, build_id, target_id))]
        with closing(read_db(self.paths[dataset])) as src:
            statuses = {r['id']: r['status'] for r in src.execute('SELECT id,status FROM jobs WHERE build_id=?', (build_id,))}
            tables = {r[0] for r in src.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            origins = [dict(r) for r in src.execute('SELECT * FROM build_origins WHERE build_id=?', (build_id,))] if 'build_origins' in tables else []
            lineage = dict(r) if 'mutation_lineage' in tables and (r := src.execute('SELECT * FROM mutation_lineage WHERE build_id=?', (build_id,)).fetchone()) else None
        for seed in seeds:
            seed['status'] = statuses.get(seed['job_id'], 'unknown')
            seed['flags'] = loads(seed['flags'], [])
        if lineage:
            for key in ('changes', 'parent_body', 'parent_targets', 'parent_origins'):
                if key in lineage: lineage[key] = loads(lineage[key])
        return {'dataset': dataset, 'build': build, 'targets': targets, 'target_id': target_id,
                'seeds': seeds, 'origins': origins, 'lineage': lineage}

    def issues(self, query):
        dataset = query.get('dataset', 'all')
        if dataset != 'all' and dataset not in DATASETS: raise ValueError('无效数据集')
        with closing(read_db(self.cache)) as db:
            rows = [dict(r) for r in db.execute('SELECT * FROM issues' + (' WHERE dataset=?' if dataset != 'all' else '') + ' ORDER BY dataset,job_id', (() if dataset == 'all' else (dataset,)))]
        return {'rows': rows}

    def raw(self, query):
        dataset = query.get('dataset'); job_id = query.get('job')
        if dataset not in DATASETS or not job_id: raise ValueError('无效记录')
        with closing(read_db(self.paths[dataset])) as db:
            row = db.execute('SELECT id,build_id,target,seed,teacher,status,attempts,result FROM jobs WHERE id=?', (job_id,)).fetchone()
            if not row: raise ValueError('找不到记录')
            result = dict(row)
            for key in ('target', 'teacher', 'result'): result[key] = loads(result[key])
            return result


def handler(view):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            request = urlsplit(self.path)
            try:
                if request.path == '/':
                    body = (ROOT / 'tools/collection_view.html').read_bytes()
                    self.send_response(200); self.send_header('Content-Type', 'text/html; charset=utf-8')
                elif request.path.startswith('/api/'):
                    params = {k: v[-1] for k, v in parse_qs(request.query, keep_blank_values=True).items()}
                    routes = {'state': lambda q: view.state(), 'overview': view.overview,
                              'battles': view.battles, 'detail': view.detail,
                              'issues': view.issues, 'raw': view.raw}
                    name = request.path.removeprefix('/api/')
                    if name not in routes: self.send_error(404); return
                    body = json.dumps(routes[name](params), ensure_ascii=False, allow_nan=False).encode()
                    self.send_response(200); self.send_header('Content-Type', 'application/json; charset=utf-8')
                elif request.path == '/favicon.ico':
                    self.send_response(204); self.end_headers(); return
                else: self.send_error(404); return
                self.send_header('Cache-Control', 'no-store')
                self.send_header('X-Content-Type-Options', 'nosniff')
                self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)
            except (ValueError, KeyError) as error:
                self.error(400, str(error))
            except (sqlite3.Error, OSError) as error:
                logging.exception('Viewer request failed'); self.error(503, str(error))

        def error(self, code, message):
            body = json.dumps({'error': message}, ensure_ascii=False).encode()
            self.send_response(code); self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body))); self.end_headers(); self.wfile.write(body)

        def log_message(self, fmt, *args):
            logging.info(fmt, *args)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path)
    parser.add_argument('--cache', type=Path)
    parser.add_argument('--localization', type=Path, default=ROOT / 'share-viewer-20260910/_build/localization.json')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=54261)
    args = parser.parse_args()
    if args.directory is None:
        args.directory = Path(loads((ROOT / 'data/collection-session.json').read_text())['project'])
    cache = args.cache or args.directory / 'viewer/index.sqlite'
    cache.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    with cache.with_suffix('.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        view = CollectionView(args.directory, cache, args.localization if args.localization.is_file() else None)
        worker = threading.Thread(target=view.run, daemon=True, name='viewer-index'); worker.start()
        server = ThreadingHTTPServer((args.host, args.port), handler(view))
        logging.info('Collection viewer: http://%s:%s/', args.host, args.port)
        try: server.serve_forever()
        except KeyboardInterrupt: pass
        finally:
            view.stop.set(); server.server_close(); worker.join(timeout=10)


if __name__ == '__main__':
    main()
