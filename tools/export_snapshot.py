"""Export a consistent, read-only view of completed native battles."""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import socket
import sqlite3

from damage_model.schema import digest
from damage_model.observation import validate_hp, validate_cards
from damage_model.schema import Build


def export_snapshot(database, output):
    database, output = Path(database), Path(output)
    with closing(sqlite3.connect(f'file:{database.resolve().as_posix()}?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        db.execute('BEGIN')
        counts = dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
        stamp = datetime.now(timezone.utc).isoformat()
        rows = db.execute("SELECT * FROM jobs WHERE status='complete' ORDER BY created,id").fetchall()
        queued_teachers = {digest(json.loads(r[0])):json.loads(r[0]) for r in db.execute('SELECT DISTINCT teacher FROM jobs')}
        builds = [{**json.loads(r['body']), 'id': r['id'], 'split': r['split']}
                  for r in db.execute("SELECT * FROM builds WHERE id IN (SELECT build_id FROM jobs WHERE status='complete')")]
        origins = []
        target_policy, selected_targets = {'name': 'whole_act_v1'}, {}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='collection_settings'").fetchone():
            policy_row = db.execute("SELECT value FROM collection_settings WHERE key='target_policy'").fetchone()
            if policy_row:
                target_policy = json.loads(policy_row[0])
        if target_policy['name'] in ('source_floor_window_v1', 'parent_source_window_v1'):
            selected_targets = {b['id']: [] for b in builds}
            table = 'mutation_target_origins' if target_policy['name'] == 'parent_source_window_v1' else 'target_origins'
            for bid, tid in db.execute(f"""SELECT DISTINCT build_id,target_id FROM {table}
                    WHERE build_id IN (SELECT build_id FROM jobs WHERE status='complete')
                    ORDER BY build_id,target_id"""):
                selected_targets[bid].append(tid)
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='build_origins'").fetchone():
            origins = [{'build_id':r['build_id'], 'run_hash':r['run_hash'], 'floor':r['floor'],
                        **json.loads(r['details'])} for r in db.execute(
                "SELECT * FROM build_origins WHERE build_id IN (SELECT build_id FROM jobs WHERE status='complete')")]
        mutation_lineage, mutation_policy_history = [], []
        if target_policy['name'] == 'parent_source_window_v1':
            from damage_model.mutations import policy_history, validate_lineage
            mutation_policy_history = policy_history(db)
            for build in builds:
                row = dict(validate_lineage(db, build['id']))
                for key in ('parent_body', 'parent_targets', 'parent_origins', 'changes'):
                    row[key] = json.loads(row[key])
                mutation_lineage.append(row)
    battles, targets, teachers = [], {}, queued_teachers
    planned_cards = {b['id']:Build.from_dict({k:v for k,v in b.items() if k not in ('id','split')}).cards for b in builds}
    for job in rows:
        result, target, teacher = (json.loads(job[k]) for k in ('result', 'target', 'teacher'))
        obs = result['trainingObservation']
        if not (result['status'] == 'Passed' and result['combatEnded'] and obs['complete']):
            raise ValueError(f"Incomplete native outcome: {job['id']}")
        validate_hp(obs, target)
        validate_cards(obs['initialBuild']['cards'], planned_cards[job['build_id']], teacher.get('collector_protocol',2))
        teacher_id = digest(teacher)
        targets[target['id']], teachers[teacher_id] = target, teacher
        battles.append({'job_id': job['id'], 'build_id': job['build_id'], 'target_id': target['id'],
            'seed': job['seed'], 'teacher_id': teacher_id, 'run_id': result['runId'],
            'initial_hp': obs['initialHp'], 'max_hp': obs['initialMaxHp'], 'final_hp': obs['finalHp'],
            'final_max_hp': obs['finalMaxHp'],
            'hp_loss': obs['netHpLoss'], 'died': obs['playerDied'], 'finished_turn': result['finishedTurn'],
            'elapsed_seconds': round(result['elapsedMilliseconds'] / 1000, 4),
            'finished_at': result['finishedAtUtc'], 'attempts': job['attempts'],
            'collector_host': result.get('collector', {}).get('host', '01 (before host tagging)')})
    assert len(battles) == counts.get('complete', 0)
    data = {'schema_version': 1, 'snapshot_at_utc': stamp, 'source_db': str(database),
            'source_host': socket.gethostname(), 'job_counts': counts, 'builds': builds,
            'targets': list(targets.values()), 'teachers': teachers, 'battles': battles, 'build_origins': origins,
            'target_policy': target_policy, 'selected_targets': selected_targets,
            'collector_host_counts': dict(Counter(r['collector_host'] for r in battles))}
    if target_policy['name'] == 'parent_source_window_v1':
        data['mutation_lineage'] = mutation_lineage
        data['mutation_policy_history'] = mutation_policy_history
        data['build_source'] = 'real_run_mutation_v1'
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + '.tmp')
    with gzip.open(temporary, 'wt', encoding='utf-8', compresslevel=6) as stream:
        json.dump(data, stream, ensure_ascii=False, separators=(',', ':'))
    temporary.replace(output)
    manifest = {k: data[k] for k in ('snapshot_at_utc', 'source_db', 'source_host', 'job_counts', 'collector_host_counts')}
    manifest.update(bytes=output.stat().st_size, sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    output.with_name('source-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default='data/collection-real-runs-v2.sqlite')
    parser.add_argument('--output', required=True)
    args = parser.parse_args()
    print(json.dumps(export_snapshot(args.db, args.output)), flush=True)
