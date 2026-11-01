"""Read collection tables without secondary job indexes into training caches.

The normal exporter remains strict. This exporter additionally supports an
explicit recovery source: unreadable rowid ranges are bisected, invalid rows
are recorded, and only observations passing the same label/card/provenance
checks are published. Collection databases are always opened read-only.
"""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import pyarrow as pa
import pyarrow.parquet as pq

from damage_model.observation import validate_cards, validate_hp
from damage_model.provenance import completed_by_expected_backend
from damage_model.schema import Build, digest
from . import ROOT
from .snapshot import BATTLE_SCHEMA


def verified_builds(output, names):
    """Reuse immutable build states previously checked against a frozen export."""
    receipt = json.loads((output.parent.parent/'verified-native-cache.json').read_text())
    if receipt.get('state') != 'verified' or Path(receipt['cache']).resolve() != output.resolve():
        raise ValueError('Build cache does not have a matching verification receipt')
    bodies, databases = {}, set()
    for name in names:
        meta = json.loads((output/(name+'.meta.json')).read_text())
        if (name not in receipt['sources'] or meta.get('verify_cards') is not True
                or receipt['sources'][name] != meta['rows']):
            raise ValueError('Unverified parent build cache: '+name)
        databases.add(str((ROOT/meta['db']).resolve()))
        with gzip.open(output/(name+'.builds.json.gz'), 'rt') as stream:
            for bid, body in json.load(stream)['builds'].items():
                bodies.setdefault(bid, body)
    return bodies, databases


def table_rows(db, table, columns, *, recover=False, reject=None, batch=64):
    """Keyset scan by the table btree; never use a secondary status index."""
    if table not in {'jobs', 'builds', 'attempts'}:
        raise ValueError('Unsupported recovery table')
    maximum = db.execute(f'SELECT rowid FROM {table} NOT INDEXED ORDER BY rowid DESC LIMIT 1').fetchone()
    if maximum is None:
        return
    maximum = maximum[0]

    def read_range(low, high):
        try:
            rows = db.execute(f'SELECT rowid AS scan_rowid,{columns} FROM {table} NOT INDEXED '
                              'WHERE rowid BETWEEN ? AND ? ORDER BY rowid', (low, high)).fetchall()
        except (sqlite3.DatabaseError, UnicodeError) as exc:
            # Busy/IO/interruption are not proof of a bad row and must not cause
            # data to be discarded. Recover only malformed pages/text.
            code = getattr(exc, 'sqlite_errorcode', 0)
            malformed = (code & 255) in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB)
            malformed = malformed or isinstance(exc, UnicodeError) or 'decode to UTF-8' in str(exc)
            if not recover or not malformed:
                raise
            if low == high:
                reject({'table': table, 'rowid': low, 'reason': 'unreadable_sqlite_row', 'error': str(exc)})
                return
            mid = (low + high) // 2
            yield from read_range(low, mid)
            yield from read_range(mid + 1, high)
            return
        yield from rows

    for low in range(1, maximum + 1, batch):
        yield from read_range(low, min(maximum, low + batch - 1))


def validated_battle(row, source, bodies, completed_at):
    teacher = json.loads(row['teacher'])
    if teacher.get('search_ms') != 8000:
        raise ValueError('Full-corpus export requires an 8000 ms teacher')
    target = json.loads(row['target'])
    result = json.loads(row['result'])
    observation = result.get('trainingObservation') or {}
    job = {'teacher': teacher, 'target': target, 'seed': row['seed']}
    if not (completed_by_expected_backend(job, result) and result.get('combatEnded') is True
            and observation.get('complete') is True):
        raise ValueError('Incomplete or mismatched backend outcome')
    validate_hp(observation, target)
    body = bodies[row['build_id']]
    build = Build.from_dict(body)
    actual_cards = observation.get('initialBuild', {}).get('cards')
    if actual_cards is None:
        raise ValueError('Missing actual starting deck')
    validate_cards(actual_cards, build.cards, teacher.get('collector_protocol', 2))
    finished_at = result.get('finishedAtUtc')
    if not finished_at and teacher.get('execution_backend') == 'standalone-managed-native':
        stamp = completed_at.get(row['id'])
        if stamp is None and not source.get('recover_invalid_rows'):
            raise ValueError('Missing completion timestamp')
        # Timestamp metadata is not the supervised label. A recovered committed
        # observation can retain a NULL timestamp rather than inventing one or
        # depending on another potentially damaged secondary index.
        if stamp is not None:
            finished_at = datetime.fromtimestamp(stamp, timezone.utc).isoformat()
    return dict(job_id=row['id'], source=source['name'], kind=source['kind'], build_id=row['build_id'],
                target_id=target['id'], act_id=body['act_id'], seed=str(row['seed']), teacher_id=digest(teacher),
                run_id=result.get('runId'), initial_hp=observation['initialHp'], max_hp=observation['initialMaxHp'],
                final_hp=observation['finalHp'], final_max_hp=observation['finalMaxHp'],
                hp_loss=observation['netHpLoss'], died=observation['playerDied'],
                finished_turn=result.get('finishedTurn'), elapsed_seconds=(result.get('elapsedMilliseconds') or 0)/1000,
                attempts=row['attempts'], finished_at=finished_at), teacher, target


def export_source(source, output, *, flush_rows=4096, read_replica=None):
    """Export a source, optionally reading a byte-verified temporary replica.

    The operator preparing the replica must verify its main/WAL/SHM bytes and
    keep the source frozen. The source identity in the cache stays original.
    Replicas use normal read-only WAL handling, never immutable=1.
    """
    name = source['name']
    path = (ROOT / (read_replica['db'] if read_replica else source['db'])).resolve()
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    recover = source.get('recover_invalid_rows', False)
    started = time.time()
    counts, rejected_counts = Counter(), Counter()
    teachers, targets, bodies, used, lineage, edges = {}, {}, {}, set(), {}, set()
    temporary = output / (name+'.battles.parquet.partial')
    reject_path = output / (name+'.rejected.jsonl')
    last_progress = 0
    rows_written = 0
    missing_completion_timestamps = 0
    db_build_fallbacks = 0

    def progress(phase, **extra):
        record = {'event': 'stream_export', 'source': name, 'phase': phase, 'rows': rows_written,
                  'job_counts': dict(counts), 'rejected': dict(rejected_counts),
                  'elapsed_s': round(time.time()-started, 1), 'updated_at': time.time(), **extra}
        (output / (name+'.progress.json')).write_text(json.dumps(record, ensure_ascii=False)+'\n')
        print(json.dumps(record), flush=True)

    with reject_path.open('w', encoding='utf-8') as rejects:
        def reject(record):
            rejected_counts[record['reason']] += 1
            rejects.write(json.dumps(record, ensure_ascii=False)+'\n')
            rejects.flush()

        with closing(sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=30)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA cache_size=-32768')
            db.execute('BEGIN')
            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            settings = {}
            if 'collection_settings' in tables:
                settings = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM collection_settings')}
            parents = source.get('verified_build_sources')
            if parents:
                progress('verified_build_cache')
                bodies, databases = verified_builds(output, parents)
                origin = settings.get('targeted_seed_backfill', {}).get('source')
                if origin is None or str(Path(origin).resolve()) not in databases:
                    raise ValueError('Backfill source differs from the verified parent build caches')
            else:
                progress('builds')
                for row in table_rows(db, 'builds', 'id,body', recover=recover, reject=reject):
                    try:
                        body = json.loads(row['body'])
                        Build.from_dict(body)
                        bodies[row['id']] = body
                    except (ValueError, KeyError, TypeError) as exc:
                        if not recover:
                            raise
                        reject({'table': 'builds', 'rowid': row['scan_rowid'], 'id': row['id'],
                                'reason': 'invalid_build', 'error': str(exc)})
            progress('completion_timestamps', stored_builds=len(bodies))
            completed_at = {}
            if not recover:
                has_index = db.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='attempts_recent'").fetchone()
                hint = 'INDEXED BY attempts_recent' if has_index else 'NOT INDEXED'
                for row in db.execute(f"SELECT job_id,finished FROM attempts {hint} WHERE status='complete'"):
                    if row['finished'] is not None:
                        completed_at[row['job_id']] = max(completed_at.get(row['job_id'], 0), row['finished'])
            progress('jobs', completion_timestamps=len(completed_at))
            buffer = []
            with pq.ParquetWriter(temporary, BATTLE_SCHEMA, compression='zstd') as writer:
                for row in table_rows(db, 'jobs', 'id,build_id,target,seed,teacher,status,result,attempts',
                                      recover=recover, reject=reject):
                    counts[row['status']] += 1
                    if row['status'] == 'complete':
                        try:
                            if parents and row['build_id'] not in bodies:
                                # Cache coverage must not silently restrict the
                                # full corpus. Fetch any later build on demand.
                                stored = db.execute('SELECT body FROM builds WHERE id=?', (row['build_id'],)).fetchone()
                                if stored is None:
                                    raise ValueError('Completed job has no planned build')
                                bodies[row['build_id']] = json.loads(stored['body'])
                                db_build_fallbacks += 1
                            battle, teacher, target = validated_battle(row, source, bodies, completed_at)
                        except (ValueError, KeyError, TypeError, OverflowError) as exc:
                            if not recover:
                                raise ValueError(f"Invalid completed label {name}/{row['id']}: {exc}") from exc
                            reject({'table': 'jobs', 'rowid': row['scan_rowid'], 'id': row['id'],
                                    'reason': 'invalid_completed_label', 'error': str(exc),
                                    'result_sha256': hashlib.sha256((row['result'] or '').encode()).hexdigest()})
                        else:
                            teachers[battle['teacher_id']] = teacher
                            targets[target['id']] = target
                            used.add(row['build_id'])
                            buffer.append(battle)
                            rows_written += 1
                            if battle['finished_at'] is None:
                                missing_completion_timestamps += 1
                            if len(buffer) >= flush_rows:
                                writer.write_table(pa.Table.from_pylist(buffer, schema=BATTLE_SCHEMA))
                                buffer.clear()
                    if time.time()-last_progress >= 30:
                        progress('jobs', rowid=row['scan_rowid'])
                        last_progress = time.time()
                if buffer:
                    writer.write_table(pa.Table.from_pylist(buffer, schema=BATTLE_SCHEMA))
            # Source/lineage failures are fatal: silently dropping edges could
            # introduce train/test leakage even when a label itself is valid.
            progress('provenance')
            if 'build_origins' in tables:
                for b, run in db.execute('SELECT build_id,run_hash FROM build_origins NOT INDEXED'):
                    if b in used:
                        edges.add(('build:'+b, 'run:'+run))
            if 'mutation_lineage' in tables:
                for row in db.execute('SELECT build_id,parent_id,size,axes,cards_changed,relics_changed,sequence '
                                      'FROM mutation_lineage NOT INDEXED'):
                    if row['build_id'] in used:
                        lineage[row['build_id']] = {k: row[k] for k in row.keys() if k != 'build_id'}
                        edges.add(('build:'+row['build_id'], 'build:'+row['parent_id']))
            if 'mutation_target_origins' in tables:
                for b, run in db.execute('SELECT build_id,run_hash FROM mutation_target_origins NOT INDEXED'):
                    if b in used:
                        edges.add(('build:'+b, 'run:'+run))
            db.execute('COMMIT')
        with gzip.open(output / (name+'.builds.json.gz'), 'wt', encoding='utf-8') as stream:
            json.dump({'builds': {b: bodies[b] for b in used}, 'lineage': lineage}, stream, separators=(',', ':'))
        with gzip.open(output / (name+'.edges.json.gz'), 'wt', encoding='utf-8') as stream:
            json.dump(sorted(edges), stream, separators=(',', ':'))
        temporary.replace(output / (name+'.battles.parquet'))
        meta = {**source, 'exported_at_utc': datetime.now(timezone.utc).isoformat(), 'job_counts': dict(counts),
                'rows': rows_written, 'builds': len(used), 'edges': len(edges), 'teachers': teachers,
                'targets': targets, 'verify_cards': True, 'scan_strategy': 'table-rowid',
                'rejected_counts': dict(rejected_counts), 'rejections': str(reject_path),
                'missing_completion_timestamps': missing_completion_timestamps,
                'db_build_fallbacks': db_build_fallbacks,
                'target_policy': settings.get('target_policy'), 'mutation_policy': settings.get('mutation_policy'),
                'contains_experimental_results': any(t.get('validation_scope') == 'isolated-experiment' for t in teachers.values()),
                'elapsed_s': round(time.time()-started, 1)}
        if read_replica:
            meta['read_replica'] = read_replica
        meta_temporary = output / (name+'.meta.json.partial')
        meta_temporary.write_text(json.dumps(meta, ensure_ascii=False, indent=2)+'\n')
        meta_temporary.replace(output / (name+'.meta.json'))
        progress('done')
        return meta


def export_or_reuse(source, output, *, force=False):
    """Serialize writers of the same source and reuse a published cache.

    Different source names may export concurrently. This lets independent
    disks prepare caches while a coordinator waits for an earlier source.
    """
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    name = source['name']
    with (output/(name+'.export.lock')).open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        meta_path = output/(name+'.meta.json')
        if meta_path.exists() and not force:
            meta = json.loads(meta_path.read_text())
            if (meta['name'] != name or meta['kind'] != source['kind']
                    or (ROOT/meta['db']).resolve() != (ROOT/source['db']).resolve()
                    or meta.get('recover_invalid_rows', False) != source.get('recover_invalid_rows', False)
                    or meta.get('verify_cards') is not True
                    or any(t.get('search_ms') != 8000 for t in meta['teachers'].values())):
                raise ValueError('Source cache identity or validation policy differs: '+name)
            for suffix in ['.battles.parquet', '.builds.json.gz', '.edges.json.gz']:
                if not (output/(name+suffix)).is_file():
                    raise ValueError('Incomplete published source cache: '+name)
            if pq.ParquetFile(output/(name+'.battles.parquet')).metadata.num_rows != meta['rows']:
                raise ValueError('Source cache row count differs from its manifest: '+name)
            print(json.dumps({'event': 'reused_source_cache', 'source': name, 'rows': meta['rows']}), flush=True)
            return meta
        # A cache is complete only after its metadata is atomically published.
        meta_path.unlink(missing_ok=True)
        return export_source(source, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--only', nargs='+')
    parser.add_argument('--force', action='store_true', help='Re-export an already completed cache')
    args = parser.parse_args()
    for source in json.loads(Path(args.config).read_text())['sources']:
        if args.only and source['name'] not in args.only:
            continue
        export_or_reuse(source, args.output, force=args.force)


if __name__ == '__main__':
    main()
