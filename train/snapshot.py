"""Export a consistent training snapshot from the 8 s collection databases.

Each source database is read once, read-only, inside a single transaction, and
streamed into a compact per-source cache (labels + build bodies + provenance
edges). The merge step then unions the sources, removes duplicate
(build, target, seed) inputs, connects builds through their source runs and
mutation parents, and assigns train/validation/test by connected component so
that no run or lineage leaks across splits.

Only ``status='complete'`` jobs with a complete native observation become rows;
every row is re-checked with the collection validators before export.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import shutil
import socket
import sqlite3
import time

import pyarrow as pa
import pyarrow.parquet as pq

from damage_model.observation import validate_cards, validate_hp
from damage_model.schema import Build, canonical, digest

from . import ROOT

SCHEMA_VERSION = 1
BATTLE_SCHEMA = pa.schema([
    ('job_id', pa.string()), ('source', pa.string()), ('kind', pa.string()), ('build_id', pa.string()),
    ('target_id', pa.string()), ('act_id', pa.string()), ('seed', pa.string()), ('teacher_id', pa.string()),
    ('run_id', pa.string()), ('initial_hp', pa.int32()), ('max_hp', pa.int32()), ('final_hp', pa.int32()),
    ('final_max_hp', pa.int32()), ('hp_loss', pa.int32()), ('died', pa.bool_()), ('finished_turn', pa.int32()),
    ('elapsed_seconds', pa.float32()), ('attempts', pa.int32()), ('finished_at', pa.string())])
BATTLE_FIELDS = BATTLE_SCHEMA.names


def _connect(path: Path):
    db = sqlite3.connect(f'file:{path.resolve().as_posix()}?mode=ro', uri=True, timeout=120)
    db.row_factory = sqlite3.Row
    return db


def _has_table(db, name):
    return db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone() is not None


def export_source(source: dict, output: Path, *, verify_cards=True, progress_every=20000):
    """Stream one database into ``output/<name>.*`` cache files."""
    name, kind, db_path = source['name'], source['kind'], ROOT / source['db']
    output.mkdir(parents=True, exist_ok=True)
    started = time.time()
    columns = {k: [] for k in BATTLE_FIELDS}
    teachers, targets, builds, edges = {}, {}, {}, []
    counts = Counter()
    lineage = {}
    print(json.dumps({'event': 'export_start', 'source': name, 'db': str(db_path.resolve())}), flush=True)
    with closing(_connect(db_path)) as db:
        db.execute('BEGIN')
        job_counts = dict(db.execute('SELECT status,COUNT(*) FROM jobs GROUP BY status'))
        print(json.dumps({'event': 'export_job_counts', 'source': name, 'job_counts': job_counts,
                          'elapsed_s': round(time.time() - started, 1)}), flush=True)
        settings = {}
        if _has_table(db, 'collection_settings'):
            settings = {k: json.loads(v) for k, v in db.execute('SELECT key,value FROM collection_settings')}
        for row in db.execute("SELECT * FROM builds WHERE id IN (SELECT DISTINCT build_id FROM jobs WHERE status='complete')"):
            builds[row['id']] = json.loads(row['body'])
        if _has_table(db, 'build_origins'):
            edges += [('build:' + b, 'run:' + r) for b, r in db.execute(
                "SELECT DISTINCT build_id,run_hash FROM build_origins WHERE build_id IN (SELECT DISTINCT build_id FROM jobs WHERE status='complete')")]
        if _has_table(db, 'mutation_lineage'):
            for row in db.execute("SELECT build_id,parent_id,size,axes,cards_changed,relics_changed,sequence FROM mutation_lineage "
                                  "WHERE build_id IN (SELECT DISTINCT build_id FROM jobs WHERE status='complete')"):
                lineage[row['build_id']] = {'parent_id': row['parent_id'], 'size': row['size'], 'axes': row['axes'],
                                            'cards_changed': row['cards_changed'], 'relics_changed': row['relics_changed'],
                                            'sequence': row['sequence']}
                edges.append(('build:' + row['build_id'], 'build:' + row['parent_id']))
            # Parent windows of mutation children also tie the child to the source runs of its parent.
            if _has_table(db, 'mutation_target_origins'):
                edges += [('build:' + b, 'run:' + r) for b, r in db.execute(
                    "SELECT DISTINCT build_id,run_hash FROM mutation_target_origins WHERE build_id IN (SELECT DISTINCT build_id FROM jobs WHERE status='complete')")]
        planned_cards = {bid: Build.from_dict(body).cards for bid, body in builds.items()}
        query = """SELECT id,build_id,target,seed,teacher,attempts,
            json_extract(result,'$.status') AS status,
            json_extract(result,'$.combatEnded') AS combat_ended,
            json_extract(result,'$.runId') AS run_id,
            json_extract(result,'$.finishedTurn') AS finished_turn,
            json_extract(result,'$.elapsedMilliseconds') AS elapsed_ms,
            json_extract(result,'$.finishedAtUtc') AS finished_at,
            json_extract(result,'$.trainingObservation.complete') AS complete,
            json_extract(result,'$.trainingObservation.initialHp') AS initial_hp,
            json_extract(result,'$.trainingObservation.initialMaxHp') AS initial_max_hp,
            json_extract(result,'$.trainingObservation.finalHp') AS final_hp,
            json_extract(result,'$.trainingObservation.finalMaxHp') AS final_max_hp,
            json_extract(result,'$.trainingObservation.netHpLoss') AS net_hp_loss,
            json_extract(result,'$.trainingObservation.playerDied') AS player_died,
            json_extract(result,'$.trainingObservation.initialBuild.cards') AS actual_cards
            FROM jobs WHERE status='complete' ORDER BY created,id"""
        for index, row in enumerate(db.execute(query), 1):
            if index % progress_every == 0:
                print(json.dumps({'event': 'export_progress', 'source': name, 'rows': index,
                                  'elapsed_s': round(time.time() - started, 1)}), flush=True)
            teacher = json.loads(row['teacher'])
            teacher_id = digest(teacher)
            teachers[teacher_id] = teacher
            target = json.loads(row['target'])
            targets[target['id']] = target
            observation = {'initialHp': row['initial_hp'], 'initialMaxHp': row['initial_max_hp'],
                           'finalHp': row['final_hp'], 'finalMaxHp': row['final_max_hp'],
                           'netHpLoss': row['net_hp_loss'], 'playerDied': bool(row['player_died']) if row['player_died'] in (0, 1) else row['player_died']}
            if not (row['status'] == 'Passed' and row['combat_ended'] == 1 and row['complete'] == 1):
                raise ValueError(f"Incomplete native outcome exported as complete: {name} {row['id']}")
            actual_cards = json.loads(row['actual_cards']) if row['actual_cards'] else None
            if observation['finalMaxHp'] != observation['initialMaxHp']:
                observation['initialBuild'] = {'cards': actual_cards or []}
            validate_hp(observation, target)
            if verify_cards:
                if actual_cards is None:
                    raise ValueError(f'Missing actual starting deck: {name} {row["id"]}')
                validate_cards(actual_cards, planned_cards[row['build_id']], teacher.get('collector_protocol', 2))
            body = builds[row['build_id']]
            values = dict(job_id=row['id'], source=name, kind=kind, build_id=row['build_id'], target_id=target['id'],
                          act_id=body['act_id'], seed=str(row['seed']), teacher_id=teacher_id, run_id=row['run_id'],
                          initial_hp=observation['initialHp'], max_hp=observation['initialMaxHp'],
                          final_hp=observation['finalHp'], final_max_hp=observation['finalMaxHp'],
                          hp_loss=observation['netHpLoss'], died=observation['playerDied'],
                          finished_turn=row['finished_turn'], elapsed_seconds=(row['elapsed_ms'] or 0) / 1000,
                          attempts=row['attempts'], finished_at=row['finished_at'])
            for key in BATTLE_FIELDS:
                columns[key].append(values[key])
            counts['rows'] += 1
        db.execute('COMMIT')
    table = pa.table({k: pa.array(v, type=BATTLE_SCHEMA.field(k).type) for k, v in columns.items()}, schema=BATTLE_SCHEMA)
    pq.write_table(table, output / f'{name}.battles.parquet', compression='zstd')
    with gzip.open(output / f'{name}.builds.json.gz', 'wt', encoding='utf-8') as stream:
        json.dump({'builds': builds, 'lineage': lineage}, stream, ensure_ascii=False, separators=(',', ':'))
    with gzip.open(output / f'{name}.edges.json.gz', 'wt', encoding='utf-8') as stream:
        json.dump(sorted(set(edges)), stream, separators=(',', ':'))
    meta = {'name': name, 'kind': kind, 'db': source['db'], 'frozen': source.get('frozen', False),
            'exported_at_utc': datetime.now(timezone.utc).isoformat(), 'host': socket.gethostname(),
            'job_counts': job_counts, 'rows': counts['rows'], 'builds': len(builds), 'edges': len(set(edges)),
            'teachers': teachers, 'targets': targets, 'settings_keys': sorted(settings),
            'target_policy': settings.get('target_policy'), 'mutation_policy': settings.get('mutation_policy'),
            'verify_cards': verify_cards, 'elapsed_s': round(time.time() - started, 1)}
    (output / f'{name}.meta.json').write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'event': 'export_done', **{k: meta[k] for k in ('name', 'rows', 'builds', 'edges', 'elapsed_s')}}), flush=True)
    return meta


class UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        a, b = self.find(a), self.find(b)
        if a != b:
            self.parent[max(a, b)] = min(a, b)


def _bucket_split(key, buckets):
    value = int(digest(key)[:8], 16) % 100
    edge = 0
    for split, width in buckets.items():
        edge += width
        if value < edge:
            return split
    return 'train'


def merge_sources(config: dict, cache: Path, output: Path, *, allow_teacher_mismatch=False):
    """Union per-source caches into one snapshot with component-based splits."""
    output.mkdir(parents=True, exist_ok=True)
    sources = config['sources']
    metas = {s['name']: json.loads((cache / f"{s['name']}.meta.json").read_text(encoding='utf-8')) for s in sources}
    teachers = {}
    for meta in metas.values():
        teachers.update(meta['teachers'])
    keys = config['teacher_compatibility_keys']
    signatures = {canonical({k: t.get(k) for k in keys}) for t in teachers.values()}
    if len(signatures) != 1 and not allow_teacher_mismatch:
        raise ValueError(f'Incompatible teacher configurations across sources: {sorted(signatures)}')
    builds, lineage, build_sources, edges = {}, {}, defaultdict(list), set()
    tables = []
    for source in sources:
        name = source['name']
        with gzip.open(cache / f'{name}.builds.json.gz', 'rt', encoding='utf-8') as stream:
            payload = json.load(stream)
        for bid, body in payload['builds'].items():
            if bid in builds and canonical(builds[bid]['body']) != canonical(body):
                # Identical build id must mean identical state (id is the digest of the state).
                if canonical(Build.from_dict(builds[bid]['body']).state()) != canonical(Build.from_dict(body).state()):
                    raise ValueError(f'Conflicting build state for {bid}')
            builds.setdefault(bid, {'body': body, 'kind': source['kind']})
            build_sources[bid].append(name)
        lineage.update({bid: {**row, 'source': name} for bid, row in payload['lineage'].items()})
        with gzip.open(cache / f'{name}.edges.json.gz', 'rt', encoding='utf-8') as stream:
            edges.update(tuple(e) for e in json.load(stream))
        tables.append(pq.read_table(cache / f'{name}.battles.parquet'))
    table = pa.concat_tables(tables)
    rows = table.to_pylist()
    # Duplicate inputs: keep the first occurrence in source order.
    seen, kept, duplicates = set(), [], Counter()
    for row in rows:
        key = (row['build_id'], row['target_id'], row['seed'])
        if key in seen:
            duplicates[row['source']] += 1
            continue
        seen.add(key)
        kept.append(row)
    # Connected components over runs, builds and mutation lineage.
    uf = UnionFind()
    for a, b in edges:
        uf.union(a, b)
    for bid in builds:
        uf.find('build:' + bid)
    members = defaultdict(list)
    for node in list(uf.parent):
        members[uf.find(node)].append(node)
    buckets = config['split_buckets']
    groups, group_split = {}, {}
    for root, nodes in members.items():
        runs = sorted(n for n in nodes if n.startswith('run:'))
        key = runs if runs else sorted(nodes)
        gid = 'component:' + digest(key)
        groups[root] = gid
        group_split[gid] = _bucket_split(key, buckets)
    build_group = {bid: groups[uf.find('build:' + bid)] for bid in builds}
    for row in kept:
        row['group'] = build_group[row['build_id']]
        row['split'] = group_split[row['group']]
    battle_table = pa.Table.from_pylist(kept)
    pq.write_table(battle_table, output / 'battles.parquet', compression='zstd')
    build_records = []
    for bid, entry in builds.items():
        build_records.append({'id': bid, 'kind': entry['kind'], 'sources': build_sources[bid],
                              'group': build_group[bid], 'split': group_split[build_group[bid]],
                              'lineage': lineage.get(bid), 'body': entry['body']})
    with gzip.open(output / 'builds.json.gz', 'wt', encoding='utf-8') as stream:
        json.dump(build_records, stream, ensure_ascii=False, separators=(',', ':'))
    targets = {}
    for meta in metas.values():
        targets.update(meta['targets'])
    (output / 'targets.json').write_text(json.dumps(targets, ensure_ascii=False, indent=1), encoding='utf-8')
    split_stats = {}
    for split in buckets:
        subset = [r for r in kept if r['split'] == split]
        split_stats[split] = {'rows': len(subset), 'builds': len({r['build_id'] for r in subset}),
                              'groups': len({r['group'] for r in subset}),
                              'pairs': len({(r['build_id'], r['target_id']) for r in subset}),
                              'by_kind': dict(Counter(r['kind'] for r in subset)),
                              'by_source': dict(Counter(r['source'] for r in subset))}
    manifest = {'schema_version': SCHEMA_VERSION, 'snapshot_at_utc': datetime.now(timezone.utc).isoformat(),
                'host': socket.gethostname(), 'sources': [{**s, **{k: metas[s['name']][k] for k in ('exported_at_utc', 'job_counts', 'rows', 'builds')}} for s in sources],
                'teachers': teachers, 'teacher_signature_keys': keys, 'teacher_signatures': sorted(signatures),
                'rows_before_dedupe': len(rows), 'rows': len(kept), 'duplicates_dropped': dict(duplicates),
                'builds': len(builds), 'components': len(group_split), 'targets': len(targets),
                'split_buckets': buckets, 'splits': split_stats,
                'label': {'normalized': 'hp_loss / max_hp', 'died': 'final_hp <= 0'},
                'files': {}}
    for path in sorted(output.glob('*')):
        if path.name != 'manifest.json' and path.is_file():
            manifest['files'][path.name] = {'bytes': path.stat().st_size, 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--config', default=str(ROOT / 'train/configs/sources.json'))
    parser.add_argument('--output', help='Snapshot directory (default: data/train-snapshots/<UTC stamp>)')
    parser.add_argument('--reuse', help='Previous snapshot directory whose frozen source caches are copied instead of re-read')
    parser.add_argument('--only', nargs='*', help='Export only these source names (merge is skipped)')
    parser.add_argument('--skip-card-verification', action='store_true', help='Skip re-validating the actual starting deck against the planned build')
    parser.add_argument('--allow-teacher-mismatch', action='store_true')
    parser.add_argument('--merge-only', action='store_true', help='Merge already exported source caches in --output without touching databases')
    parser.add_argument('--cache', help='Directory holding per-source caches (default: <output>/sources)')
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding='utf-8'))
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    output = Path(args.output) if args.output else ROOT / 'data/train-snapshots' / stamp
    cache = Path(args.cache) if args.cache else output / 'sources'
    cache.mkdir(parents=True, exist_ok=True)
    for source in config['sources']:
        if args.merge_only or (args.only and source['name'] not in args.only):
            continue
        previous = Path(args.reuse) / 'sources' if args.reuse else None
        if source.get('frozen') and previous and (previous / f"{source['name']}.meta.json").exists():
            for suffix in ('.battles.parquet', '.builds.json.gz', '.edges.json.gz', '.meta.json'):
                shutil.copy2(previous / (source['name'] + suffix), cache / (source['name'] + suffix))
            print(json.dumps({'event': 'reused_frozen_source', 'source': source['name'], 'from': str(previous)}), flush=True)
            continue
        export_source(source, cache, verify_cards=not args.skip_card_verification)
    if args.only:
        return
    manifest = merge_sources(config, cache, output, allow_teacher_mismatch=args.allow_teacher_mismatch)
    print(json.dumps({k: manifest[k] for k in ('rows', 'builds', 'components', 'duplicates_dropped', 'splits')}, ensure_ascii=False, indent=2))
    print(str(output))


if __name__ == '__main__':
    main()
