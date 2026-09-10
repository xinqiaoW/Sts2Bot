"""Read-only health and provenance checks for the separate mutation queue."""
from collections import Counter
import json
from pathlib import Path
import sqlite3
import time

from .catalog import Catalog
from .mutations import policy_history, require_mutation_database, validate_lineage
from .observation import validate_hp
from .provenance import sha256
from .schema import canonical, digest


def check_mutations(session, active, root):
    root = Path(root); now = time.time()
    assert session['mutation_db'] == active['mutation_db']
    assert session['mutation_policy'] == active['mutation_policy']
    policy = json.loads((root/session['mutation_policy']).read_text())
    catalog = Catalog.load(root/'catalogs/game-0.111.0.raw.json', root/session['config'])
    with sqlite3.connect(f"file:{root/session['mutation_db']}?mode=ro", uri=True) as db:
        db.row_factory = sqlite3.Row
        require_mutation_database(db)
        assert json.loads(db.execute("SELECT value FROM collection_settings WHERE key='mutation_policy'").fetchone()[0]) == policy
        history = policy_history(db)
        assert {r[0] for r in db.execute('SELECT DISTINCT teacher FROM jobs')} <= {canonical(session['teacher'])}
        counts = dict(db.execute('SELECT status,count(*) FROM jobs GROUP BY status'))
        missing = db.execute("""SELECT count(*) FROM jobs j WHERE status IN ('pending','running') AND
            (NOT EXISTS(SELECT 1 FROM mutation_lineage l WHERE l.build_id=j.build_id) OR
             NOT EXISTS(SELECT 1 FROM mutation_target_origins t WHERE t.build_id=j.build_id AND t.target_id=json_extract(j.target,'$.id')))""").fetchone()[0]
        rows = db.execute("SELECT a.result,j.build_id,j.target FROM attempts a JOIN jobs j ON j.id=a.job_id WHERE a.finished>? AND a.status='complete'", (now-90,)).fetchall()
        workers, checked = set(), set()
        for row in rows:
            if row['build_id'] not in checked: validate_lineage(db, row['build_id'], catalog); checked.add(row['build_id'])
            result = json.loads(row['result']); obs = result['trainingObservation']
            planned = json.loads(db.execute('SELECT body FROM builds WHERE id=?', (row['build_id'],)).fetchone()[0]); actual = obs['initialBuild']
            assert result['status'] == 'Passed' and result['combatEnded'] is True and obs['complete'] is True
            validate_hp(obs, json.loads(row['target']))
            assert obs['initialHp'] == obs['initialMaxHp'] == 70
            assert actual['character'] == 'SILENT' and actual['ascension'] == 10 and actual['actId'] == planned['act_id']
            assert Counter((c['id'],c['upgradeLevel'],c.get('enchantmentId') or '',c.get('enchantmentAmount',0)) for c in actual['cards']) == Counter((c['id'],c['upgrade'],c.get('enchantment_id') or '',c.get('enchantment_amount',0)) for c in planned['cards'])
            assert [r['id'] for r in actual['relics']] == [r['id'] for r in planned['relics']]
            assert all(canonical(r.get('counters',{})) == canonical(dict(p['state'])) for r,p in zip(actual['relics'],planned['relics']))
            workers.add(result['collector']['worker'])
        quarantines = []
        for q in db.execute('SELECT * FROM job_quarantines'):
            job = dict(db.execute('SELECT * FROM jobs WHERE id=?', (q['job_id'],)).fetchone())
            attempts = [dict(r) for r in db.execute('SELECT * FROM attempts WHERE job_id=? ORDER BY id', (q['job_id'],))]
            assert job == {**json.loads(q['original_job']), 'status':'quarantined'} and digest(attempts) == q['attempts_sha256']
            for attempt in attempts:
                result = json.loads(attempt['result'])
                folder = root/policy['evidence_directory']/q['job_id']/result['runId']
                evidence = json.loads((folder/'failure.json').read_text())
                assert evidence['result'] == result and sha256(folder/'native.log') == evidence['diagnosis']['log_sha256']
            quarantines.append(q['job_id'])
        recent = dict(db.execute('SELECT status,count(*) FROM attempts WHERE finished>? GROUP BY status', (now-600,)))
    state = json.loads((root/session['mutation_backup_state']).read_text())
    errors = []
    if counts.get('failed') or missing: errors.append('mutation_jobs_or_scope')
    pid = session['mutation_backup_pid']; cmdpath = Path('/proc')/str(pid)/'cmdline'
    args = cmdpath.read_bytes().decode().split('\0') if cmdpath.is_file() else []
    if not args or 'tools.local_backup' not in args: errors.append('mutation_backup_process')
    else:
        assert args[args.index('--db')+1] == session['mutation_db']
        assert args[args.index('--directory')+1] == session['mutation_backup_destination']
        assert args[args.index('--state')+1] == session['mutation_backup_state']
    if state['state'] != 'saved' or now-state['updated'] > 420: errors.append('mutation_backup')
    else:
        directory = Path(state['directory']); manifest = state['manifest']
        assert manifest['database'] == Path(session['mutation_db']).name
        assert sha256(directory/manifest['database']) == manifest['sha256']
        assert json.loads((directory/Path(session['mutation_policy']).name).read_text()) == policy
        with sqlite3.connect(f"file:{directory/manifest['database']}?mode=ro", uri=True) as backup:
            backup.row_factory = sqlite3.Row
            assert backup.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
            assert policy_history(backup) == history
            for q in backup.execute('SELECT * FROM job_quarantines'):
                attempts = [dict(r) for r in backup.execute('SELECT * FROM attempts WHERE job_id=? ORDER BY id', (q['job_id'],))]
                assert digest(attempts) == q['attempts_sha256']
    return {'counts':counts,'mutation_policy_history':history,'out_of_scope_active':missing,'recent_90s_verified':len(rows),
            'recent_worker_names':sorted(workers),'recent_600s_attempts':recent,
            'quarantined_job_ids':quarantines,'backup':state,'alerts':errors}
