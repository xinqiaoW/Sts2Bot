"""Public bounded exports, CRC validation, durable pages and restartable cursors."""
from datetime import datetime, timezone
from contextlib import contextmanager
from email.utils import parsedate_to_datetime
from http.client import IncompleteRead
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
import zlib
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .run_import import check_run, import_run, RunRejected

ENDPOINT = 'https://spire-codex.com/api/exports/runs'
USER_AGENT = 'Sts2DamageModel/0.1 (public run research; no human labels)'
MAX_PAGE_BYTES = 32 * 1024**2
MAX_RAW_BYTES = 128 * 1024**2


def atomic(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def decode_page(data):
    with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
        raw = stream.read(MAX_RAW_BYTES + 1)
    if len(raw) > MAX_RAW_BYTES:
        raise ValueError('Run export exceeds decompressed page bound')
    return [json.loads(line) for line in raw.splitlines() if line]


def retry_delay(value, now):
    try:
        delay = float(value)
    except (ValueError, TypeError):
        try:
            delay = parsedate_to_datetime(value).timestamp() - now
        except (ValueError, TypeError, AttributeError):
            delay = 300
    return max(31, delay)


@contextmanager
def rate_state(path):
    """Serialize reservations across independent source cursors on this host."""
    import fcntl
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.with_suffix('.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = json.loads(path.read_text()) if path.exists() else {'next_request_at': 0}
        yield state
        atomic(path, state)


def reserve_request(path, now):
    if path is None:
        return None
    with rate_state(path) as state:
        if now < state['next_request_at']:
            return state['next_request_at']
        state['next_request_at'] = now + 31
    return None


def defer_requests(path, until):
    if path is not None:
        with rate_state(path) as state:
            state['next_request_at'] = max(state['next_request_at'], until)


def defer_invalid_download(directory, pointer, state, page_key, url, data, following, error, rate_path):
    """Keep rejected transport bytes separate; retry exactly the same cursor."""
    failed = directory / 'failed-downloads'
    failed.mkdir(exist_ok=True)
    checksum = hashlib.sha256(data).hexdigest()
    payload = failed / (page_key + '-' + checksum + '.jsonl.gz')
    if not payload.exists():
        payload.write_bytes(data)
    state['next_request_at'] = time.time() + 300
    state['last_error'] = f'{type(error).__name__}: {error}'
    evidence = failed / f'{time.time_ns()}.json'
    atomic(evidence, {'url': url, 'request_scope': {k: state[k] for k in ('start', 'end', 'cursor', 'page_number')},
                     'response_next_cursor': following, 'payload': payload.name, 'bytes': len(data),
                     'sha256': checksum, 'error': state['last_error'], 'retry_at': state['next_request_at']})
    atomic(pointer, state)
    defer_requests(rate_path, state['next_request_at'])
    return {'state': 'waiting_source', 'error': state['last_error'],
            'retry_at': state['next_request_at'], 'evidence': str(evidence)}


def sync_page(store, catalog, teacher, source_dir, start, *, end=None, follow=True, rate_path=None):
    if follow and (end is not None or start is None):
        raise ValueError('Live source needs a start and manages its own end')
    directory = Path(source_dir)
    directory.mkdir(parents=True, exist_ok=True)
    pointer = directory / 'cursor.json'
    state = json.loads(pointer.read_text()) if pointer.exists() else {
        'start':start, 'end':utc_now() if follow else end, 'cursor':None, 'next_request_at':0,
        'follow':follow, 'complete':False,
        'page_number':0, 'endpoint':ENDPOINT}
    if state.get('follow', True) != follow or (not follow and (state['start'], state['end']) != (start, end)):
        raise ValueError('Existing source cursor has a different scan scope; use a separate directory')
    if state.get('complete'):
        return {'state':'backfill_complete', 'page':state['page_number']}
    now = time.time()
    if now < state['next_request_at']:
        return {'state':'waiting_source', 'retry_at':state['next_request_at']}
    page_key = hashlib.sha256(json.dumps([state['start'], state['end'], state['cursor']]).encode()).hexdigest()
    page = directory / (page_key + '.jsonl.gz')
    receipt = directory / (page_key + '.receipt.json')
    if not (page.exists() and receipt.exists()):
        retry_at = reserve_request(rate_path, now)
        if retry_at is not None:
            return {'state':'waiting_source', 'retry_at':retry_at, 'reason':'shared_export_rate_limit'}
        params = {'limit':1000}
        for key in ('start', 'end'):
            if state[key] is not None:
                params[key] = state[key]
        if state['cursor']:
            params['cursor'] = state['cursor']
        url = ENDPOINT + '?' + urlencode(params)
        # A durable rate guard also survives failed downloads and interruption.
        state['next_request_at'] = now + 31
        atomic(pointer, state)
        data, following = b'', None
        try:
            with urlopen(Request(url, headers={'User-Agent':USER_AGENT, 'Accept':'application/gzip'}), timeout=45) as response:
                data = response.read(MAX_PAGE_BYTES + 1)
                following = response.headers.get('X-Next-Cursor')
            if len(data) > MAX_PAGE_BYTES:
                raise ValueError('Run export exceeds compressed page bound')
            decode_page(data)  # Reaching EOF checks the gzip trailer and CRC.
        except (EOFError, gzip.BadGzipFile, zlib.error, IncompleteRead) as error:
            if isinstance(error, IncompleteRead):
                data = error.partial
            return defer_invalid_download(directory, pointer, state, page_key, url, data,
                                          following, error, rate_path)
        except HTTPError as error:
            if error.code == 429 or error.code in (500, 502, 503, 504):
                state['next_request_at'] = time.time() + retry_delay(error.headers.get('Retry-After'), time.time())
                state['last_error'] = f'HTTP {error.code}'
                atomic(pointer, state)
                defer_requests(rate_path, state['next_request_at'])
                return {'state':'waiting_source', 'error':state['last_error'], 'retry_at':state['next_request_at']}
            raise
        except (URLError, TimeoutError) as error:
            state['next_request_at'] = time.time() + 300
            state['last_error'] = str(error)
            atomic(pointer, state)
            defer_requests(rate_path, state['next_request_at'])
            return {'state':'waiting_source', 'error':str(error), 'retry_at':state['next_request_at']}
        temporary = page.with_suffix('.tmp')
        temporary.write_bytes(data)
        temporary.replace(page)
        atomic(receipt, {'url':url, 'sha256':hashlib.sha256(data).hexdigest(),
                         'next_cursor':following, 'downloaded_at':time.time()})
    data = page.read_bytes()
    metadata = json.loads(receipt.read_text())
    if hashlib.sha256(data).hexdigest() != metadata['sha256']:
        raise ValueError('Cached source page failed checksum')
    runs = decode_page(data)
    reports = []
    for run in runs:
        try:
            check_run(run)
        except RunRejected:
            continue
        run_hash = run.get('run_hash')
        if not isinstance(run_hash, str) or not run_hash or any(c not in '0123456789abcdef' for c in run_hash):
            raise ValueError('Export is missing a valid run_hash')
        reports.append(import_run(store, catalog, teacher, run, run_hash, metadata['url']))
    state['cursor'] = metadata['next_cursor']
    state['page_number'] += 1
    state.pop('last_error', None)
    if not state['cursor']:
        if follow:
            state['start'] = state['end']
            state['end'] = utc_now()
            state['next_request_at'] = time.time() + 300
        else:
            state['complete'] = True
    atomic(pointer, state)
    report = {'state':'page_imported', 'page':state['page_number'], 'source_runs':len(runs),
              'matching_runs':len(reports), 'scheduled_now':sum(r['scheduled_now'] for r in reports),
              'accepted_floors':sum(r['accepted_floors'] for r in reports if not r.get('already_imported')),
              'rejected_runs':sum('rejected' in r for r in reports), 'next_request_at':state['next_request_at']}
    atomic(directory / 'latest.json', report)
    return report
