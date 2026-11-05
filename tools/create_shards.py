"""Split the 1.4M native battle corpus into 3 balanced, self-contained SQLite shards for distributed simulation."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import sqlite3
import time

import numpy as np
import pyarrow.parquet as pq

from damage_model.schema import canonical

ROOT = Path(__file__).resolve().parents[1]


def digest(items):
    return hashlib.sha256(canonical(items).encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, default=Path('/data/pl/Sts2Bot-training-20261031/snapshot'))
    parser.add_argument('--bundle', type=Path, default=Path('/data1/pl/ImageTask/wxq/Projects/standalone-rollout-readiness-20260929/candidate-release-v5'))
    parser.add_argument('--out-dir', type=Path, default=Path('/data1/pl/ImageTask/wxq/Projects/Sts2Bot_dist_collection/shards'))
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    teacher = json.loads((args.bundle / 'teacher.json').read_text(encoding='utf-8'))
    teacher_canonical = canonical(teacher)

    print('Loading targets...')
    targets = json.loads((args.snapshot / 'targets.json').read_text(encoding='utf-8'))
    targets_canonical = {k: canonical(v) for k, v in targets.items()}

    print('Reading battles.parquet...')
    battles_table = pq.read_table(
        args.snapshot / 'battles.parquet',
        columns=['job_id', 'source', 'build_id', 'target_id', 'act_id', 'seed', 'group', 'split'],
    )
    df = battles_table.to_pandas()
    is_native = ~df['source'].str.startswith('sim-')
    native_df = df[is_native].copy()
    n_total = len(native_df)
    print(f'Total native battles to shard: {n_total:,}')

    # Greedy bin-packing by lineage/component group
    print('Bin-packing connected components into 3 balanced shards...')
    group_counts = native_df['group'].value_counts()
    shard_groups = [set(), set(), set()]
    shard_sums = [0, 0, 0]

    for g, count in group_counts.items():
        idx = int(np.argmin(shard_sums))
        shard_groups[idx].add(g)
        shard_sums[idx] += count

    print(f'Shard battle counts: {shard_sums}')

    # Assign shard index to dataframe
    group_to_shard = {}
    for s_idx, g_set in enumerate(shard_groups):
        for g in g_set:
            group_to_shard[g] = s_idx
    native_df['shard'] = native_df['group'].map(group_to_shard)

    needed_build_ids = set(native_df['build_id'])
    print(f'Unique builds needed across native shards: {len(needed_build_ids):,}')

    print('Reading builds.json.gz...')
    t0 = time.time()
    with gzip.open(args.snapshot / 'builds.json.gz', 'rt', encoding='utf-8') as f:
        all_builds_list = json.load(f)
    print(f'Loaded {len(all_builds_list):,} builds in {time.time() - t0:.1f}s')

    # Index relevant builds: id -> (family, split, canonical_body)
    build_data = {}
    for item in all_builds_list:
        bid = item['id']
        if bid in needed_build_ids:
            body_dict = item['body']
            build_data[bid] = (
                item.get('family') or body_dict.get('family', ''),
                item.get('split', 'train'),
                canonical(body_dict),
            )
    print(f'Retained {len(build_data):,} build records for sharding')

    now = time.time()
    manifest_shards = []

    for s_idx in range(3):
        shard_name = f'shard_{s_idx + 1}'
        db_path = args.out_dir / f'{shard_name}.sqlite'
        if db_path.exists():
            db_path.unlink()
        print(f'\nWriting {shard_name} to {db_path}...')

        shard_df = native_df[native_df['shard'] == s_idx]
        shard_build_ids = set(shard_df['build_id'])
        print(f'  Battles: {len(shard_df):,}, Unique builds: {len(shard_df_build_ids := shard_build_ids):,}')

        con = sqlite3.connect(db_path)
        con.execute('PRAGMA synchronous=OFF')
        con.execute('PRAGMA journal_mode=MEMORY')
        con.executescript('''
            CREATE TABLE builds(id TEXT PRIMARY KEY,family TEXT,split TEXT,body TEXT);
            CREATE TABLE jobs(id TEXT PRIMARY KEY,build_id TEXT,target TEXT,seed TEXT,
                teacher TEXT,status TEXT DEFAULT 'pending',lease TEXT,lease_until REAL,attempts INTEGER DEFAULT 0,
                result TEXT,created REAL,FOREIGN KEY(build_id) REFERENCES builds(id));
            CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY,job_id TEXT,lease TEXT,status TEXT,result TEXT,finished REAL);
            CREATE TABLE IF NOT EXISTS collection_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        ''')

        # Insert builds
        build_rows = [
            (bid, build_data[bid][0], build_data[bid][1], build_data[bid][2])
            for bid in shard_build_ids
        ]
        con.executemany('INSERT INTO builds VALUES(?,?,?,?)', build_rows)
        print(f'  Inserted {len(build_rows):,} builds')

        # Prepare jobs
        print('  Generating job IDs and inserting jobs...')
        job_rows = []
        for row in shard_df.itertuples(index=False):
            bid = row.build_id
            tid = row.target_id
            seed_str = str(row.seed)
            target_obj = targets[tid]
            tgt_canon = targets_canonical[tid]
            jid = digest([bid, target_obj['id'], seed_str, teacher])
            job_rows.append((jid, bid, tgt_canon, seed_str, teacher_canonical, 'pending', now))

        con.executemany(
            'INSERT OR IGNORE INTO jobs(id,build_id,target,seed,teacher,status,created) VALUES(?,?,?,?,?,?,?)',
            job_rows,
        )
        print(f'  Inserted {len(job_rows):,} jobs')

        print('  Creating indexes and setting journal_mode=WAL...')
        con.executescript('''
            CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status,created);
            CREATE INDEX IF NOT EXISTS jobs_build ON jobs(build_id);
            CREATE INDEX IF NOT EXISTS jobs_teacher ON jobs(teacher);
            CREATE INDEX IF NOT EXISTS attempts_recent ON attempts(finished,status,job_id);
            CREATE INDEX IF NOT EXISTS attempts_job ON attempts(job_id);
            PRAGMA journal_mode=WAL;
            PRAGMA synchronous=NORMAL;
        ''')
        con.close()
        file_size_mb = db_path.stat().st_size / (1024 * 1024)
        print(f'  Finished {shard_name}.sqlite ({file_size_mb:.1f} MB)')

        manifest_shards.append({
            'shard_index': s_idx + 1,
            'file': f'{shard_name}.sqlite',
            'battles': len(shard_df),
            'unique_builds': len(shard_build_ids),
            'size_mb': round(file_size_mb, 1),
            'act_counts': shard_df['act_id'].value_counts().to_dict(),
        })

    manifest = {
        'created_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'total_battles': n_total,
        'teacher_backend': teacher['execution_backend'],
        'teacher_sha256': hashlib.sha256(teacher_canonical.encode()).hexdigest(),
        'shards': manifest_shards,
    }
    manifest_path = args.out_dir / 'manifest.json'
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
    print(f'\nWrote manifest to {manifest_path}')
    print('All 3 shards created successfully!')


if __name__ == '__main__':
    main()
