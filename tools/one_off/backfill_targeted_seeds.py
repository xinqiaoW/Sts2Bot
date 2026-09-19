"""One-off seed extension into separate queues; never update source databases.

Run as ``python -m tools.one_off.backfill_targeted_seeds`` from the project root.
No production module imports this file. Remove this directory after collection.
"""
import argparse
from collections import Counter
from contextlib import ExitStack, closing
import json
from pathlib import Path
import sqlite3
import sys
import time

from damage_model.catalog import Catalog
from damage_model.mutations import MUTATION, validate_lineage
from damage_model.provenance import teacher_for
from damage_model.schema import Build, canonical, digest
from damage_model.store import Store


PROVENANCE_TABLES = ('build_origins', 'target_origins', 'mutation_lineage',
                     'mutation_target_origins', 'mutation_focus')
ADAPTER_KEYS = {'collector_protocol', 'collector_source', 'collector_sha256'}


def pair_statistics(pairs):
    """Count builds separately from their distinct encounter pairs."""
    per_build = Counter(bid for bid, _ in set(pairs))
    return {'eligible_builds': len(per_build), 'eligible_pairs': sum(per_build.values()),
            'eligible_pairs_per_build': dict(sorted(Counter(per_build.values()).items()))}


def connect_readonly(path):
    db = sqlite3.connect(Path(path).resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA query_only=ON')
    db.execute('BEGIN')
    return db


def has_table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def check_teacher(old, new):
    if old == new:
        return
    # The archived protocol-2 labels remain archived. New battles use the
    # configured protocol-3 observer, with exactly the same game/search policy.
    if (old.get('collector_protocol') != 2 or new.get('collector_protocol') != 3
            or {k: v for k, v in old.items() if k not in ADAPTER_KEYS}
            != {k: v for k, v in new.items() if k not in ADAPTER_KEYS}):
        raise ValueError('Incompatible source teacher: only the existing protocol 2 -> 3 adapter transition is allowed')


def manifest_for(paths, catalog, teacher):
    if catalog.config['initial_seeds_per_pair'] != 4 or not catalog.encounter_seed_counts:
        raise ValueError('This one-off tool requires the four-seed baseline and a configured encounter seed policy')
    if set(catalog.encounter_seed_counts.values()) != {24}:
        raise ValueError('This one-off tool only supports extending 4 seeds to 24')
    return {'version': 1, 'sources': [str(p) for p in paths],
            'battle_seed': catalog.config['battle_seed'], 'seed_indices': [4, 24],
            'targets': sorted([act, tid] for act, tid in catalog.encounter_seed_counts),
            'teacher': teacher}


def scan(db, ids, occupied, completed, owners=None, source_index=None):
    """Track input identities across adapters and all job statuses, not outcomes."""
    slots = ','.join('?' for _ in ids)
    teachers = set()
    coverage = Counter()
    for row in db.execute(f"""SELECT build_id,json_extract(target,'$.id') AS tid,seed,status,teacher
            FROM jobs WHERE json_extract(target,'$.id') IN ({slots})""", ids):
        key = (row['build_id'], row['tid'])
        occupied.setdefault(key, set()).add(row['seed'])
        teachers.add(row['teacher'])
        coverage['jobs:' + row['status']] += 1
        if row['status'] == 'complete':
            completed.setdefault(key, set()).add(row['seed'])
            if owners is not None:
                owners.setdefault(key, source_index)
    if has_table(db, 'prior_collected_inputs'):
        for row in db.execute(f"""SELECT build_id,target_id,seed,source_status,source_teacher
                FROM prior_collected_inputs WHERE target_id IN ({slots})""", ids):
            key = (row['build_id'], row['target_id'])
            occupied.setdefault(key, set()).add(row['seed'])
            teachers.add(row['source_teacher'])
            coverage['prior:' + row['source_status']] += 1
            if row['source_status'] == 'complete':
                completed.setdefault(key, set()).add(row['seed'])
                if owners is not None:
                    owners.setdefault(key, source_index)
    return teachers, dict(coverage)


def check_output(db, manifest, source):
    row = db.execute("SELECT value FROM collection_settings WHERE key='targeted_seed_backfill'").fetchone()
    if row is None or json.loads(row[0]) != {**manifest, 'source': str(source)}:
        raise ValueError('Output is not a matching backfill queue; use a new output directory')
    if any(json.loads(r[0]) != manifest['teacher'] for r in db.execute('SELECT DISTINCT teacher FROM jobs')):
        raise ValueError('Backfill queue teacher changed')


def prepare_output(path, source_db, manifest, source):
    store = Store(path)
    try:
        db = store.db
        # This connection only builds the one-off queue. Keep durable commits,
        # but avoid the default 2 MiB cache spilling random index pages.
        db.execute('PRAGMA cache_size=-262144')
        db.execute('PRAGMA wal_autocheckpoint=16384')
        row = db.execute("SELECT value FROM collection_settings WHERE key='targeted_seed_backfill'").fetchone()
        if row is not None:
            check_output(db, manifest, source)
            return store
        if db.execute('SELECT 1 FROM builds LIMIT 1').fetchone() or db.execute('SELECT 1 FROM jobs LIMIT 1').fetchone():
            raise ValueError('Backfill output must be new or a matching resumable queue')
        with db:
            for table in PROVENANCE_TABLES:
                schema = source_db.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
                if schema and not has_table(db, table):
                    db.execute(schema[0])
            # Preserve mutation policy boundaries/sequence for validate_lineage.
            db.executemany('INSERT OR REPLACE INTO collection_settings VALUES(?,?)',
                           source_db.execute('SELECT key,value FROM collection_settings'))
            db.execute('INSERT OR REPLACE INTO collection_settings VALUES(?,?)',
                       ('targeted_seed_backfill', canonical({**manifest, 'source': str(source)})))
            db.execute('''CREATE TABLE IF NOT EXISTS backfill_origins(
                build_id TEXT,target_id TEXT,source_database TEXT,original_completed_seeds TEXT,
                PRIMARY KEY(build_id,target_id))''')
        return store
    except BaseException:
        store.db.close()
        raise


def copy_build(db, source_db, row):
    db.execute('INSERT OR IGNORE INTO builds VALUES(?,?,?,?)', tuple(row))
    stored = db.execute('SELECT * FROM builds WHERE id=?', (row['id'],)).fetchone()
    if tuple(stored) != tuple(row):
        raise ValueError('Backfill build provenance changed')
    for table in PROVENANCE_TABLES:
        if not has_table(source_db, table):
            continue
        for origin in source_db.execute(f'SELECT * FROM {table} WHERE build_id=?', (row['id'],)):
            slots = ','.join('?' for _ in origin)
            db.execute(f'INSERT OR IGNORE INTO {table} VALUES({slots})', tuple(origin))


def backfill(sources, output_dir, catalog, teacher, *, apply=False, progress=None):
    paths = [Path(p).resolve(strict=True) for p in sources]
    output_dir = Path(output_dir).resolve()
    if len(set(paths)) != len(paths) or len({p.stem for p in paths}) != len(paths):
        raise ValueError('Source paths and database stems must be unique')
    outputs = [output_dir / (p.stem + '.backfill.sqlite') for p in paths]
    if set(paths) & set(outputs):
        raise ValueError('Sources and outputs must be separate')
    manifest = manifest_for(paths, catalog, teacher)
    manifest_path = output_dir / 'backfill-manifest.json'
    ids = sorted({tid for _, tid in catalog.encounter_seed_counts})
    original_seeds = {digest(['battle', manifest['battle_seed'], i])[:16] for i in range(4)}
    occupied, completed, owners = {}, {}, {}
    with ExitStack() as stack:
        if apply:
            import fcntl
            output_dir.mkdir(parents=True, exist_ok=True)
            lock = stack.enter_context((output_dir / '.backfill.lock').open('a+'))
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if manifest_path.exists() and json.loads(manifest_path.read_text(encoding='utf-8')) != manifest:
            raise ValueError('Output directory is not a matching backfill; use a new output directory')
        databases = [stack.enter_context(closing(connect_readonly(p))) for p in paths]
        source_teachers = []
        source_coverage = []
        source_builds = []
        for index, db in enumerate(databases):
            if progress:
                progress({'event': 'scan_source', 'source': str(paths[index])})
            if apply and db.execute("SELECT 1 FROM jobs WHERE status='running' LIMIT 1").fetchone():
                raise ValueError('Pause and drain source collectors before applying the one-off backfill')
            encoded, coverage = scan(db, ids, occupied, completed, owners, index)
            for value in encoded:
                check_teacher(json.loads(value), teacher)
            source_teachers.append([json.loads(v) for v in sorted(encoded)])
            source_coverage.append(coverage)
            source_builds.append({r[0] for r in db.execute('SELECT id FROM builds')})
        # Existing output statuses (including running/failed/quarantined) all
        # count as occupied, so retries never reset attempts or duplicate work.
        existing_output_jobs = [0] * len(outputs)
        for index, (path, source) in enumerate(zip(outputs, paths)):
            if path.exists():
                with closing(connect_readonly(path)) as db:
                    check_output(db, manifest, source)
                    existing_output_jobs[index] = db.execute('SELECT count(*) FROM jobs').fetchone()[0]
                    scan(db, ids, occupied, {}, None)
        report = {'apply': apply, 'seed_indices': [4, 24], 'target_encounters': len(catalog.encounter_seed_counts),
                  'eligible_pairs': 0, 'partial_original_pairs': 0, 'missing_original_seeds': 0,
                  'jobs_to_add': 0, 'jobs_added': 0, 'existing_extra_seeds': 0,
                  'sources': [], 'by_encounter': {}}
        work = [[] for _ in paths]
        eligible = [set() for _ in paths]
        per_target = Counter()
        for pair_index, ((bid, tid), index) in enumerate(sorted(owners.items())):
            if progress and pair_index % 10000 == 0:
                progress({'event': 'validate_pairs', 'checked': pair_index, 'total': len(owners)})
            old_complete = completed[(bid, tid)] & original_seeds
            if not old_complete:
                continue
            source_db = databases[index]
            row = source_db.execute('SELECT * FROM builds WHERE id=?', (bid,)).fetchone()
            if row is None:
                raise ValueError(f'Missing source build: {bid}')
            build = Build.from_dict(json.loads(row['body']))
            if (build.act_id, tid) not in catalog.encounter_seed_counts:
                continue
            if build.id != bid or row['family'] != build.family or row['split'] != build.split:
                raise ValueError(f'Source build identity or split mismatch: {bid}')
            catalog.validate(build)
            if build.mutation == MUTATION:
                validate_lineage(source_db, bid, catalog)
            elif build.mutation != 'spire_codex_run_v1':
                raise ValueError('Backfill only supports real-run and recorded mutation builds')
            target = next(t for t in catalog.targets(build) if t['id'] == tid)
            extras = catalog.battle_seeds(build.act_id, tid)[4:]
            missing = [s for s in extras if s not in occupied[(bid, tid)]]
            report['eligible_pairs'] += 1
            eligible[index].add((bid, tid))
            report['partial_original_pairs'] += len(old_complete) < 4
            report['missing_original_seeds'] += 4 - len(old_complete)
            report['existing_extra_seeds'] += len(extras) - len(missing)
            report['jobs_to_add'] += len(missing)
            per_target[f'{build.act_id}/{tid}'] += len(missing)
            if missing:
                work[index].append((row, target, missing, sorted(old_complete)))
        report['by_encounter'] = dict(sorted(per_target.items()))
        report.update(pair_statistics(set().union(*eligible)))
        report['stored_unique_builds'] = len(set().union(*source_builds))
        report['original_seed_slots'] = report['eligible_pairs'] * 4
        report['original_completed_seed_slots'] = report['original_seed_slots'] - report['missing_original_seeds']
        report['extra_seed_slots'] = report['eligible_pairs'] * 20
        if report['jobs_to_add'] + report['existing_extra_seeds'] != report['extra_seed_slots']:
            raise ValueError('Backfill seed counts do not reconcile with eligible pairs')
        if apply and not manifest_path.exists():
            temporary = manifest_path.with_suffix('.tmp')
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temporary.replace(manifest_path)
        # All sources, teachers, builds and lineages were checked before any
        # queue is written. Commit batches of whole pairs to avoid hundreds of
        # thousands of fsyncs; an interrupted batch rolls back in its entirety.
        for index, pairs in enumerate(work):
            detail = {'source': str(paths[index]), 'output': str(outputs[index]),
                      'pairs_to_extend': len(pairs), 'jobs_to_add': sum(len(p[2]) for p in pairs),
                      'stored_builds': len(source_builds[index]), **pair_statistics(eligible[index]),
                      'existing_output_jobs': existing_output_jobs[index],
                      'expected_output_jobs': existing_output_jobs[index] + sum(len(p[2]) for p in pairs),
                      'original_teachers': source_teachers[index], 'target_input_records': source_coverage[index]}
            report['sources'].append(detail)
            if not apply or not pairs:
                continue
            if progress:
                progress({'event': 'write_queue', 'output': str(outputs[index]), 'pairs': len(pairs)})
            store = prepare_output(outputs[index], databases[index], manifest, paths[index])
            try:
                for start in range(0, len(pairs), 1000):
                    store._begin_write('targeted_seed_backfill')
                    with store.db:
                        for row, target, seeds, old_complete in pairs[start:start + 1000]:
                            copy_build(store.db, databases[index], row)
                            store.db.execute('INSERT OR IGNORE INTO backfill_origins VALUES(?,?,?,?)',
                                             (row['id'], target['id'], str(paths[index]), canonical(old_complete)))
                            for seed in seeds:
                                jid = digest([row['id'], target['id'], seed, teacher])
                                report['jobs_added'] += store.db.execute('''INSERT OR IGNORE INTO jobs
                                    (id,build_id,target,seed,teacher,created) VALUES(?,?,?,?,?,?)''',
                                    (jid, row['id'], canonical(target), seed, canonical(teacher), time.time())).rowcount
                            if json.loads(row['body'])['mutation'] == MUTATION:
                                validate_lineage(store.db, row['id'], catalog)
                    if progress:
                        progress({'event': 'queue_progress', 'output': str(outputs[index]),
                                  'pairs_written': min(start + 1000, len(pairs)), 'pairs': len(pairs),
                                  'total_jobs_added': report['jobs_added']})
            finally:
                store.db.close()
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sources', nargs='+', required=True,
                        help='Newest first; archived versions can be covered by preserved prior_collected_inputs plus build provenance')
    parser.add_argument('--output-dir', required=True)
    parser.add_argument('--catalog', default='catalogs/game-0.111.0.raw.json')
    parser.add_argument('--config', default='configs/real-runs-8s.json')
    parser.add_argument('--teacher', default='configs/teacher.json')
    parser.add_argument('--apply', action='store_true', help='Create/resume separate pending queues; never starts workers')
    parser.add_argument('--report', help='Optional JSON report path')
    args = parser.parse_args()
    catalog = Catalog.load(args.catalog, args.config)
    report = backfill(args.sources, args.output_dir, catalog, teacher_for(catalog, args.teacher), apply=args.apply,
                      progress=lambda event: print(json.dumps(event), file=sys.stderr, flush=True))
    text = json.dumps(report, ensure_ascii=False, indent=2)
    if args.report:
        Path(args.report).write_text(text + '\n', encoding='utf-8')
    print(text)


if __name__ == '__main__':
    main()
