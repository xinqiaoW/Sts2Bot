"""Freeze new real inputs and isolated three-queue rollout workloads."""
import argparse
from collections import Counter, defaultdict
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
import time
from types import SimpleNamespace

from standalone_rollout_metrics import identity, read, sha, write
from standalone_rollout_provenance import native_files, verify_candidate


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('bundle', 'source', 'prior-plan', 'directory', 'native-source', 'native-runtime', 'trace-dll', 'benchmark', 'correctness-audit'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--real-builds', type=int, default=16000)
    parser.add_argument('--mutation-builds', type=int, default=1000)
    args = parser.parse_args()
    if args.directory.exists():
        parser.error('Use a new campaign directory; preparation never overwrites evidence')
    bundle = args.bundle.resolve(strict=True)
    spec = importlib.util.spec_from_file_location('frozen_release', bundle / 'release_tool.py')
    release = importlib.util.module_from_spec(spec); spec.loader.exec_module(release)
    manifest = release.verify(bundle)
    provenance = dict(bundle=str(bundle), correctnessAudit=identity(args.correctness_audit),
                      priorPlan=identity(args.prior_plan), nativeSource=str(args.native_source.resolve()),
                      nativeRuntime=str(args.native_runtime.resolve()), nativeRuntimeIdentity=identity(args.native_runtime),
                      nativeFiles=native_files(args.native_source), traceDll=identity(args.trace_dll),
                      benchmark=identity(args.benchmark))
    verify_candidate(provenance)
    sys.path.insert(0, str(bundle))
    from damage_model.catalog import Catalog
    from damage_model.schema import Build, canonical, digest
    from damage_model.store import Store
    from damage_model.run_import import init_sources
    from damage_model.target_scope import require_policy
    from damage_model.mutations import Generator
    from damage_model.worker import request_for
    root = Path(__file__).resolve().parents[1]
    sys.path.insert(0, str(root / 'experiments/standalone-simulator'))
    from build_panel_contract import composition_key
    catalog = Catalog.load(bundle / 'catalogs/game-0.111.0.raw.json', bundle / 'configs/real-runs-8s.json')
    teacher = read(bundle / 'teacher.json')
    assert catalog.config['search_dop'] == 1 and catalog.config['short_search_budget_ms'] == 8000
    folder = args.directory.resolve(); folder.mkdir(parents=True)
    control = folder / 'control'; control.mkdir()
    for name in ('standalone_rollout_metrics.py', 'standalone_rollout_provenance.py', 'prepare_standalone_rollout.py',
                 'run_standalone_rollout.py', 'standalone_rollout_audit.py'):
        shutil.copyfile(Path(__file__).with_name(name), control / name)
    shutil.copyfile(root / 'experiments/standalone-simulator/replay_evidence.py', control / 'replay_evidence.py')
    shutil.copyfile(root / 'experiments/standalone-simulator/run_backend_rollback.py', control / 'run_backend_rollback.py')
    source_path = folder / 'source.sqlite'
    with sqlite3.connect(args.source.resolve().as_uri() + '?mode=ro', uri=True) as source:
        with sqlite3.connect(source_path) as target:
            source.backup(target, pages=4096)
    source = sqlite3.connect(source_path.as_uri() + '?mode=ro', uri=True)
    source.row_factory = sqlite3.Row
    prior = read(args.prior_plan)
    excluded = {v['compositionKey'] for v in prior['builds'].values()}
    origins = defaultdict(list)
    for row in source.execute('SELECT * FROM target_origins'):
        origins[row['build_id']].append(tuple(row))
    candidates = []
    rejected = Counter()
    for bid, body in source.execute('SELECT id,body FROM builds ORDER BY id'):
        build = Build.from_dict(json.loads(body))
        try:
            catalog.validate(build)
        except ValueError:
            rejected['catalog'] += 1; continue
        targets = {t['id']: t for t in catalog.targets(build)}
        ids = sorted({r[4] for r in origins[bid]} & targets.keys())
        if not ids:
            rejected['no_source_window'] += 1; continue
        target = targets[ids[0]]
        request = request_for(dict(id=bid, build=build.to_dict(), target=target,
                                   seed=catalog.battle_seeds(build.act_id, target['id'])[0]), catalog.config)
        key = composition_key(request)
        if key in excluded:
            rejected['prior_or_duplicate_composition'] += 1; continue
        excluded.add(key)
        candidates.append((digest(['rollout-v1', key]), build, ids, targets, key))
    by_act = defaultdict(list)
    for item in sorted(candidates, key=lambda x: x[0]):
        by_act[item[1].act_id].append(item)
    chosen = []
    for index in range(max(map(len, by_act.values()))):
        for act in sorted(by_act):
            if index < len(by_act[act]):
                chosen.append(by_act[act][index])
        if len(chosen) >= args.real_builds:
            break
    chosen = chosen[:args.real_builds]
    assert len(chosen) == args.real_builds
    templates = folder / 'templates'; templates.mkdir()
    real = Store(templates / 'real.sqlite'); init_sources(real); require_policy(real, catalog.config)
    real.db.execute('CREATE TABLE rollout_inputs(build_id TEXT PRIMARY KEY, composition TEXT, source_sha256 TEXT)')
    cases_by_target = defaultdict(list)
    encoded_teacher = canonical(teacher)
    with real.db:
        for index, (rank, build, ids, targets, key) in enumerate(chosen):
            encoded = canonical(build.to_dict())
            real.db.execute('INSERT INTO builds VALUES(?,?,?,?)', (build.id, build.family, build.split, encoded))
            real.db.execute('INSERT INTO rollout_inputs VALUES(?,?,?)', (build.id, key, digest(build.to_dict())))
            real.db.executemany('INSERT INTO target_origins VALUES(?,?,?,?,?)', origins[build.id])
            for row in source.execute('SELECT * FROM build_origins WHERE build_id=?', (build.id,)):
                real.db.execute('INSERT INTO build_origins VALUES(?,?,?,?)', tuple(row))
            for tid in ids:
                seeds = catalog.battle_seeds(build.act_id, tid)
                for seed_index, seed in enumerate(seeds):
                    jid = digest([build.id, tid, str(seed), teacher])
                    # Interleave distinct builds before later seeds, independent of outcomes.
                    real.db.execute('INSERT INTO jobs(id,build_id,target,seed,teacher,created) VALUES(?,?,?,?,?,?)',
                                    (jid, build.id, canonical(targets[tid]), str(seed), encoded_teacher,
                                     seed_index * len(chosen) + index))
                cases_by_target[tid].append(dict(build=build.to_dict(), target=targets[tid], seed=str(seeds[0]),
                                                 jobId=digest([build.id, tid, str(seeds[0]), teacher]), rank=rank,
                                                 complexity=len(build.cards) + 2 * len(build.relics)))
        # Original source rows remain immutable in source.sqlite; retain referenced run payloads too.
        for (run_hash,) in real.db.execute('SELECT DISTINCT run_hash FROM build_origins').fetchall():
            row = source.execute('SELECT * FROM source_runs WHERE hash=?', (run_hash,)).fetchone()
            if row:
                real.db.execute('INSERT OR IGNORE INTO source_runs VALUES(?,?,?,?,?,?)', tuple(row))
    assert len(cases_by_target) == 80, sorted(cases_by_target)
    paired = []
    for tid, items in sorted(cases_by_target.items()):
        # One ordinary hash-selected input and one complex input for each formal target.
        ordinary = min(items, key=lambda x: x['rank'])
        complex_case = min((x for x in items if x['jobId'] != ordinary['jobId']),
                           key=lambda x: (-x['complexity'], x['rank']))
        paired.extend([ordinary, complex_case])
    paired.sort(key=lambda x: digest(['paired-order', x['jobId']]))
    write(folder / 'paired-inputs.json', paired)
    real.db.close()
    mutation_reports = {}
    stores = [Store(templates / (name + '.sqlite')) for name in ('mutation', 'targeted')]
    for name, store, filename in zip(('mutation', 'targeted'), stores, ('mutations-8s.json', 'mutations-targeted-8s.json')):
        policy = read(bundle / 'configs' / filename)
        policy['evidence_directory'] = str(folder / 'soak/evidence' / name)
        generator = Generator(SimpleNamespace(db=source), store, catalog, teacher, policy)
        generator.avoid_stores = [SimpleNamespace(db=sqlite3.connect((templates / 'real.sqlite').as_uri() + '?mode=ro', uri=True)),
                                  *[other for other in stores if other is not store]]
        mutation_reports[name] = generator.refill(args.mutation_builds)
        generator.avoid_stores[0].db.close()
    for store in stores:
        store.db.close()
    source.close()
    for path in templates.glob('*.sqlite'):
        with sqlite3.connect(path) as database:
            database.execute('PRAGMA wal_checkpoint(TRUNCATE)')
    source_path.chmod(0o444)
    plan = dict(schema='standalone-rollout/v2', directory=str(folder), **provenance,
                releaseManifest=identity(bundle / 'release.json'), source=identity(source_path),
                pairedInputs=identity(folder / 'paired-inputs.json'),
                templates={p.stem: identity(p) for p in templates.glob('*.sqlite')},
                control={p.name: sha(p) for p in control.glob('*.py')},
                realBuilds=len(chosen), rejections=dict(rejected),
                mutations=mutation_reports, concurrencyOrder=[8,16,24,32,32,24,16,8],
                soakSeconds=86400, minimumCompleted=10000, auditModulo=100,
                scope='Isolated real/real/mutation/targeted queues. New real compositions exclude the accepted 10,500-build panel. Formal source-window targets and seeds retained. No production pointers or original attempts changed.')
    write(folder / 'plan.json', plan)
    print(json.dumps({'prepared': True, 'directory': str(folder), 'realBuilds': len(chosen),
                      'pairedInputs': len(paired), 'mutations': mutation_reports}), flush=True)


if __name__ == '__main__':
    main()
