"""Select encounters actually recorded near each accepted precombat inventory."""
from collections import Counter
import json
import time

from .schema import Build, canonical, digest

WINDOW_POLICY = 'source_floor_window_v1'
LEGACY_POLICY = 'whole_act_v1'
EXCLUDED_STATUS = 'excluded_target'


def policy_for(config):
    name = config.get('target_policy', LEGACY_POLICY)
    if name == LEGACY_POLICY:
        return {'name': name}
    radius = config.get('target_floor_radius')
    if name != WINDOW_POLICY or type(radius) is not int or radius != 2:
        raise ValueError('Unsupported target policy; expected source floors +/-2')
    return {'name': name, 'radius': radius, 'same_act': True}


def require_policy(store, config):
    policy = policy_for(config)
    row = store.db.execute("SELECT value FROM collection_settings WHERE key='target_policy'").fetchone()
    if row and json.loads(row[0]) != policy:
        raise ValueError('Target policy changed; migrate the queue before importing')
    if not row:
        if policy['name'] != LEGACY_POLICY and store.db.execute('SELECT 1 FROM jobs LIMIT 1').fetchone():
            raise ValueError('Existing whole-act queue requires target policy migration')
        with store.db:
            store.db.execute('INSERT INTO collection_settings VALUES(?,?)', ('target_policy', canonical(policy)))
    return policy


def recorded_floors(run):
    floors = []
    for act_index, nodes in enumerate(run['map_point_history']):
        act = run['acts'][act_index]
        if not isinstance(act, str) or not act.startswith('ACT.'):
            raise ValueError('Invalid source act')
        for node in nodes:
            targets = sorted({room['model_id'].split('.', 1)[1] for room in node.get('rooms', [])
                              if str(room.get('model_id', '')).startswith('ENCOUNTER.')})
            floors.append({'floor': len(floors)+1, 'act': act_index+1,
                           'act_id': act.split('.', 1)[1], 'targets': targets})
    return floors


def window_for_origin(floors, origin, catalog, radius=2):
    number = origin['floor']
    if type(number) is not int or not 1 <= number <= len(floors):
        raise ValueError('Origin floor is missing from source history')
    center = floors[number-1]
    if (center['act'], center['act_id']) != (origin['act'], origin['act_id']):
        raise ValueError('Origin act does not match source history')
    if origin['target'] not in center['targets']:
        raise ValueError('Origin encounter does not match source history')
    allowed = {t['id']: t for t in catalog.acts[origin['act_id']]['encounters']}
    if origin['target'] not in allowed:
        raise ValueError('Origin encounter is not in the act catalog')
    selected, skipped = [], []
    for floor in floors[max(0, number-radius-1):number+radius]:
        if (floor['act'], floor['act_id']) != (center['act'], center['act_id']):
            continue
        for target in floor['targets']:
            record = {'floor': floor['floor'], 'target': target}
            if target in allowed:
                selected.append(record)
            else:
                skipped.append({**record, 'reason': 'Encounter not in the act catalog'})
    targets = [allowed[target] for target in sorted({r['target'] for r in selected})]
    return targets, {'policy': WINDOW_POLICY, 'radius': radius,
                     'origin_floor': number, 'selected': selected, 'skipped': skipped}


def save_target_origins(database, build_id, run_hash, selection):
    database.executemany('INSERT OR IGNORE INTO target_origins VALUES(?,?,?,?,?)',
        [(build_id, run_hash, selection['origin_floor'], r['floor'], r['target'])
         for r in selection['selected']])


def plan_window(database, catalog):
    """Read-only preview over all preserved origins, including earlier revisions."""
    policy = policy_for(catalog.config)
    if policy['name'] != WINDOW_POLICY:
        raise ValueError('Configure source_floor_window_v1 before planning')
    sources = {r['hash']: recorded_floors(json.loads(r['body']))
               for r in database.execute('SELECT hash,body FROM source_runs')}
    builds = {r['id']: Build.from_dict(json.loads(r['body']))
              for r in database.execute('SELECT id,body FROM builds')}
    pairs, origins, ignored = set(), [], []
    for row in database.execute('SELECT * FROM build_origins ORDER BY build_id,run_hash,floor'):
        origin = json.loads(row['details'])
        if origin['floor'] != row['floor']:
            raise ValueError('Origin floor index mismatch')
        build = builds[row['build_id']]
        if (origin['act'], origin['act_id']) != (build.act, build.act_id):
            raise ValueError('Origin/build act mismatch')
        targets, selection = window_for_origin(sources[row['run_hash']], origin, catalog, policy['radius'])
        pairs.update((build.id, t['id']) for t in targets)
        origins.append({'build_id': build.id, 'run_hash': row['run_hash'], **selection})
        ignored.extend({'run_hash': row['run_hash'], **r} for r in selection['skipped'])
    if set(builds) - {bid for bid, _ in pairs}:
        raise ValueError('An existing build has no verified source target window')
    by_status = Counter()
    outside = []
    for row in database.execute('SELECT id,build_id,target,status FROM jobs'):
        selected = (row['build_id'], json.loads(row['target'])['id']) in pairs
        by_status[(row['status'], selected)] += 1
        if row['status'] == 'pending' and not selected:
            outside.append(row['id'])
    per_build = Counter(bid for bid, _ in pairs)
    report = {'policy': policy, 'source_runs': len(sources), 'builds': len(builds),
              'origins': len(origins), 'selected_pairs': len(pairs),
              'selected_battles': len(pairs)*catalog.config['initial_seeds_per_pair'],
              'targets_per_build': dict(sorted(Counter(per_build.values()).items())),
              'jobs_by_scope': {f'{status}:{"selected" if selected else "outside"}': n
                                for (status, selected), n in sorted(by_status.items())},
              'exclude_pending': len(outside), 'skipped_neighbors': ignored}
    return {'report': report, 'pairs': pairs, 'origins': origins, 'exclude_ids': outside, 'builds': builds}


def migrate_window(store, catalog, teacher):
    """Called with supervisor/worker locks held; never alter outcomes or attempts."""
    db = store.db
    db.execute('BEGIN IMMEDIATE')
    try:
        counts = store.counts()
        if counts.get('running') or counts.get('failed'):
            raise ValueError('Drain the pool and diagnose failed jobs before migration')
        if {r[0] for r in db.execute('SELECT DISTINCT teacher FROM jobs')} - {canonical(teacher)}:
            raise ValueError('Frozen teacher mismatch')
        plan = plan_window(db, catalog)
        prior = db.execute("SELECT value FROM collection_settings WHERE key='target_policy'").fetchone()
        if prior and json.loads(prior[0]) not in ({'name': LEGACY_POLICY}, plan['report']['policy']):
            raise ValueError('Unsupported target policy migration')
        stamp = time.time()
        for origin in plan['origins']:
            save_target_origins(db, origin['build_id'], origin['run_hash'], origin)
        for jid in plan['exclude_ids']:
            db.execute('INSERT INTO job_scope_changes(job_id,previous_status,new_status,reason,changed_at) VALUES(?,?,?,?,?)',
                       (jid, 'pending', EXCLUDED_STATUS, WINDOW_POLICY, stamp))
            db.execute('UPDATE jobs SET status=? WHERE id=? AND status=\'pending\'', (EXCLUDED_STATUS, jid))
        seeds = [digest(['battle', catalog.config['battle_seed'], j])[:16]
                 for j in range(catalog.config['initial_seeds_per_pair'])]
        added = restored = 0
        for bid, tid in sorted(plan['pairs']):
            build = plan['builds'][bid]
            target = next(t for t in catalog.targets(build) if t['id'] == tid)
            for seed in seeds:
                jid = digest([bid, tid, seed, teacher])
                added += db.execute('INSERT OR IGNORE INTO jobs(id,build_id,target,seed,teacher,created) VALUES(?,?,?,?,?,?)',
                    (jid, bid, canonical(target), seed, canonical(teacher), stamp)).rowcount
                row = db.execute('SELECT status FROM jobs WHERE id=?', (jid,)).fetchone()
                if row[0] == EXCLUDED_STATUS:
                    db.execute('UPDATE jobs SET status=\'pending\' WHERE id=?', (jid,))
                    db.execute('INSERT INTO job_scope_changes(job_id,previous_status,new_status,reason,changed_at) VALUES(?,?,?,?,?)',
                        (jid, EXCLUDED_STATUS, 'pending', WINDOW_POLICY, stamp))
                    restored += 1
        db.execute('INSERT OR REPLACE INTO collection_settings VALUES(?,?)',
                   ('target_policy', canonical(plan['report']['policy'])))
        report = {**plan['report'], 'added': added, 'restored': restored,
                  'before_counts': counts, 'after_counts': store.counts(), 'migrated_at': stamp}
        db.commit()
        return report
    except BaseException:
        db.rollback()
        raise
