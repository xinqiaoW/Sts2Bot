"""One controller shares its request budget between live and historical sources."""
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import time

from .run_source import atomic, sync_page


def read(path, default=None):
    return json.loads(Path(path).read_text()) if Path(path).exists() else default


def historical_plan(cutoff):
    end = datetime.fromisoformat(cutoff.replace('Z', '+00:00'))
    if end.tzinfo is None:
        raise ValueError('Historical boundary requires an explicit timezone')
    end = end.astimezone(timezone.utc)
    # Fill the nearest missing week first, then cover the complete public corpus,
    # including legacy runs with no submitted_at (excluded by date filters).
    return [{'name':'recent-history', 'start':(end-timedelta(days=7)).isoformat(), 'end':end.isoformat()},
            {'name':'full-archive', 'start':None, 'end':None}]


def sync_sources(store, catalog, teacher, live_dir, live_start, backfill_dir):
    live_dir, directory = Path(live_dir), Path(backfill_dir)
    directory.mkdir(parents=True, exist_ok=True)
    pointer = directory / 'plan.json'
    plan = historical_plan(live_start)
    state = read(pointer, {'schema':1, 'cutoff':live_start, 'phases':plan, 'phase_index':0,
                           'state':'collecting_history'})
    if state['schema'] != 1 or state['cutoff'] != live_start or state['phases'] != plan:
        raise ValueError('Historical plan differs from its saved scope')
    rate_path = directory / 'export-rate.json'
    if not rate_path.exists():
        # Respect the existing live cursor's guard when enabling historical scans.
        live = read(live_dir/'cursor.json', {})
        atomic(rate_path, {'next_request_at':max(time.time(), live.get('next_request_at',0))})
    now = time.time()
    rate = read(rate_path)
    if now < rate['next_request_at']:
        atomic(pointer, state)
        return {'state':'waiting_source', 'retry_at':rate['next_request_at'], 'reason':'shared_export_rate_limit'}
    live = read(live_dir/'cursor.json', {})
    # Live pages have priority when due; their 300s window wait leaves room for
    # historical pages, each subject to the same persistent 31s request gate.
    if now >= live.get('next_request_at',0):
        report = sync_page(store,catalog,teacher,live_dir,live_start,rate_path=rate_path)
        atomic(pointer, state)
        return {'source_stream':'live', **report}
    while state['phase_index'] < len(plan):
        phase = plan[state['phase_index']]
        report = sync_page(store,catalog,teacher,directory/phase['name'],phase['start'],
                           end=phase['end'],follow=False,rate_path=rate_path)
        cursor = read(directory/phase['name']/'cursor.json', {})
        if cursor.get('complete'):
            state['phase_index'] += 1
        state['updated'] = time.time()
        if state['phase_index'] == len(plan):
            state['state'] = 'history_complete'
        atomic(pointer,state)
        if report['state'] == 'backfill_complete':
            continue
        result = {'source_stream':phase['name'], 'history_state':state['state'], **report}
        atomic(directory/'latest.json',result)
        return result
    atomic(pointer,state)
    return {'state':'waiting_source','reason':'historical_scan_complete',
            'retry_at':live.get('next_request_at',now+300)}
