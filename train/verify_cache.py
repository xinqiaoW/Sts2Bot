"""Verify reused per-source caches against their frozen snapshot's hashes."""
import argparse
from collections import defaultdict
import gzip
import hashlib
import json
from pathlib import Path

import pyarrow.compute as pc
import pyarrow.parquet as pq

from damage_model.schema import Build, digest
from .snapshot import UnionFind, _bucket_split


def sha256(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024*1024), b''):
            value.update(block)
    return value.hexdigest()


def verify(snapshot, cache):
    snapshot, cache = Path(snapshot), Path(cache)
    manifest = json.loads((snapshot/'manifest.json').read_text())
    for name in ['battles.parquet', 'builds.json.gz', 'targets.json']:
        if sha256(snapshot/name) != manifest['files'][name]['sha256']:
            raise ValueError('Frozen snapshot checksum mismatch: '+name)
    reference = pq.read_table(snapshot/'battles.parquet')
    with gzip.open(snapshot/'builds.json.gz', 'rt') as stream:
        builds = {b['id']: b for b in json.load(stream)}
    uf, source_rows = UnionFind(), {}
    for source in manifest['sources']:
        name = source['name']
        meta = json.loads((cache/(name+'.meta.json')).read_text())
        table = pq.read_table(cache/(name+'.battles.parquet'))
        expected = reference.filter(pc.equal(reference['source'], name))
        if (meta.get('verify_cards') is not True or table.num_rows != source['rows']
                or not table.equals(expected.select(table.column_names).cast(table.schema))):
            raise ValueError('Source labels differ from the verified frozen snapshot: '+name)
        for key, teacher in meta['teachers'].items():
            if manifest['teachers'].get(key) != teacher:
                raise ValueError('Teacher identity mismatch: '+name)
        with gzip.open(cache/(name+'.builds.json.gz'), 'rt') as stream:
            payload = json.load(stream)
        for bid, body in payload['builds'].items():
            if Build.from_dict(body).state() != Build.from_dict(builds[bid]['body']).state():
                raise ValueError('Cached build state differs from the frozen snapshot: '+bid)
        with gzip.open(cache/(name+'.edges.json.gz'), 'rt') as stream:
            for a, b in json.load(stream):
                uf.union(a, b)
        source_rows[name] = table.num_rows
        print(json.dumps({'event': 'source_cache_verified', 'source': name, 'rows': table.num_rows}), flush=True)
    for bid in builds:
        uf.find('build:'+bid)
    members = defaultdict(list)
    for node in list(uf.parent):
        members[uf.find(node)].append(node)
    groups = {}
    for root, nodes in members.items():
        key = sorted(n for n in nodes if n.startswith('run:')) or sorted(nodes)
        groups[root] = ('component:'+digest(key), _bucket_split(key, manifest['split_buckets']))
    for bid, build in builds.items():
        if groups[uf.find('build:'+bid)] != (build['group'], build['split']):
            raise ValueError('Cached provenance changes the frozen train/test split: '+bid)
    return {'state': 'verified', 'snapshot': str(snapshot.resolve()), 'cache': str(cache.resolve()),
            'rows': sum(source_rows.values()), 'sources': source_rows, 'builds': len(builds),
            'checks': ['snapshot_sha256', 'label_values', 'teachers', 'build_states', 'provenance_groups_and_splits']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True)
    parser.add_argument('--cache', required=True)
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    result = verify(args.snapshot, args.cache)
    Path(args.output).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
