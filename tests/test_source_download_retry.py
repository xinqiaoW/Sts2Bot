"""Bad network payloads never enter imports or advance the source cursor."""
import gzip
import hashlib
from http.client import IncompleteRead
from io import BytesIO
import json
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip('fcntl')
from damage_model import run_source


class Response(BytesIO):
    headers = {'X-Next-Cursor': 'next-good-page'}


@pytest.mark.parametrize('failure', ['truncated', 'crc', 'deflate', 'incomplete_http'])
def test_invalid_download_backoff_then_same_page_success(tmp_path, monkeypatch, failure):
    now = [1000.0]
    monkeypatch.setattr(run_source.time, 'time', lambda: now[0])
    good = gzip.compress(b'{"run_hash":"aa"}\n')
    bad = good[:-8]
    if failure == 'crc': bad = good[:-8] + bytes([good[-8] ^ 1]) + good[-7:]
    if failure == 'deflate': bad = good[:10] + b'\x07' + good[11:]
    replies = [IncompleteRead(bad, 8) if failure == 'incomplete_http' else Response(bad), Response(good)]
    requested, imported = [], []
    def fetch(request, timeout):
        requested.append(request.full_url)
        response = replies.pop(0)
        if isinstance(response, Exception): raise response
        return response
    monkeypatch.setattr(run_source, 'urlopen', fetch)
    monkeypatch.setattr(run_source, 'check_run', lambda r: None)
    def accept(*args):
        imported.append(args[3])
        return {'scheduled_now': 4, 'accepted_floors': 1}
    monkeypatch.setattr(run_source, 'import_run', accept)
    cache = tmp_path/'source'; cache.mkdir()
    initial = {'start': None, 'end': None, 'cursor': 'same-page', 'page_number': 340,
               'next_request_at': 0, 'follow': False, 'complete': False, 'endpoint': run_source.ENDPOINT}
    run_source.atomic(cache/'cursor.json', initial)
    gate = tmp_path/'rate.json'
    def sync(): return run_source.sync_page(None, None, None, cache, None, follow=False, rate_path=gate)
    report = sync()
    assert report['state'] == 'waiting_source' and report['retry_at'] == 1300
    state = json.loads((cache/'cursor.json').read_text())
    assert {k: state[k] for k in initial if k != 'next_request_at'} == {k: v for k,v in initial.items() if k != 'next_request_at'}
    assert not imported and not list(cache.glob('*.jsonl.gz')) and not list(cache.glob('*.receipt.json'))
    evidence = json.loads(next((cache/'failed-downloads').glob('*.json')).read_text())
    assert evidence['sha256'] == hashlib.sha256(bad).hexdigest()
    assert (cache/'failed-downloads'/evidence['payload']).read_bytes() == bad
    assert json.loads(gate.read_text())['next_request_at'] == 1300
    now[0] = 1299
    assert sync()['state'] == 'waiting_source' and len(requested) == 1
    now[0] = 1300
    assert sync()['state'] == 'page_imported'
    assert requested[0] == requested[1] and parse_qs(urlparse(requested[1]).query)['cursor'] == ['same-page']
    state = json.loads((cache/'cursor.json').read_text())
    assert state['page_number'] == 341 and state['cursor'] == 'next-good-page' and 'last_error' not in state
    assert imported == [{'run_hash': 'aa'}]


def test_valid_gzip_with_invalid_json_still_requires_diagnosis(tmp_path, monkeypatch):
    monkeypatch.setattr(run_source, 'urlopen', lambda *a, **kw: Response(gzip.compress(b'not JSON\n')))
    with pytest.raises(json.JSONDecodeError):
        run_source.sync_page(None, None, None, tmp_path, None, follow=False)
    assert not list(tmp_path.glob('*.receipt.json'))
    assert json.loads((tmp_path/'cursor.json').read_text())['page_number'] == 0


def test_cached_corruption_is_not_silently_redownloaded(tmp_path, monkeypatch):
    monkeypatch.setattr(run_source, 'urlopen', lambda *a, **kw: Response(gzip.compress(b'')))
    monkeypatch.setattr(run_source.time, 'time', lambda: 1000)
    run_source.sync_page(None, None, None, tmp_path, None, follow=False)
    state = json.loads((tmp_path/'cursor.json').read_text())
    state.update(cursor=None, next_request_at=0, page_number=0)
    run_source.atomic(tmp_path/'cursor.json', state)
    next(tmp_path.glob('*.jsonl.gz')).write_bytes(b'corrupt cache')
    with pytest.raises(ValueError, match='Cached source page failed checksum'):
        run_source.sync_page(None, None, None, tmp_path, None, follow=False)
