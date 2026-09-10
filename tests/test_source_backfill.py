from io import BytesIO
import gzip
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse

import pytest

pytest.importorskip('fcntl')
from damage_model import run_source, source_backfill


class Response(BytesIO):
    def __init__(self, rows=(), cursor=None):
        super().__init__(gzip.compress(b''.join((json.dumps(r)+'\n').encode() for r in rows)))
        self.headers = {'X-Next-Cursor':cursor}


@pytest.fixture
def network(monkeypatch):
    now = [1000.0]
    calls = []
    responses = []
    monkeypatch.setattr(run_source.time, 'time', lambda:now[0])
    def fetch(request, timeout):
        calls.append(parse_qs(urlparse(request.full_url).query))
        reply = responses.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply
    monkeypatch.setattr(run_source, 'urlopen', fetch)
    return now, calls, responses


def test_finite_history_resumes_same_window_until_header_exhausted(tmp_path, network):
    now,calls,responses = network
    responses.extend([Response(cursor='continue-even-empty'),Response()])
    cache=tmp_path/'history'
    args=(None,None,None,cache,'2026-08-29T00:00:00Z')
    first=run_source.sync_page(*args,end='2026-09-05T00:00:00Z',follow=False)
    assert first['source_runs']==0
    assert not json.loads((cache/'cursor.json').read_text())['complete']
    now[0]+=31
    run_source.sync_page(*args,end='2026-09-05T00:00:00Z',follow=False)
    state=json.loads((cache/'cursor.json').read_text())
    assert state['complete'] and state['page_number']==2
    assert calls[0]['start']==calls[1]['start'] and calls[0]['end']==calls[1]['end']
    assert calls[1]['cursor']==['continue-even-empty']
    assert run_source.sync_page(*args,end='2026-09-05T00:00:00Z',follow=False)['state']=='backfill_complete'
    assert len(calls)==2
    with pytest.raises(ValueError,match='different scan scope'):
        run_source.sync_page(*args,end='2026-09-06T00:00:00Z',follow=False)


def test_full_archive_omits_dates_and_keeps_legacy_rows(tmp_path, network, monkeypatch):
    _,calls,responses=network
    responses.append(Response([{'run_hash':'aa','legacy':True}]))
    seen=[]
    monkeypatch.setattr(run_source,'check_run',lambda r:None)
    def import_run(store,catalog,teacher,run,run_hash,url):
        seen.append(run)
        return {'scheduled_now':4,'accepted_floors':1}
    monkeypatch.setattr(run_source,'import_run',import_run)
    report=run_source.sync_page(None,None,None,tmp_path,None,follow=False)
    assert calls==[{'limit':['1000']}] and seen==[{'run_hash':'aa','legacy':True}]
    assert report['scheduled_now']==4


def test_live_and_history_share_rate_gate_and_429_backoff(tmp_path, network):
    now,calls,responses=network
    responses.extend([Response(cursor='live-next'),HTTPError('fixture',429,'limited',{'Retry-After':'120'},None)])
    gate=tmp_path/'shared-rate.json'
    run_source.sync_page(None,None,None,tmp_path/'live','2026-09-05T00:00:00Z',rate_path=gate)
    report=run_source.sync_page(None,None,None,tmp_path/'history',None,follow=False,rate_path=gate)
    assert report['reason']=='shared_export_rate_limit' and len(calls)==1
    now[0]+=31
    report=run_source.sync_page(None,None,None,tmp_path/'history',None,follow=False,rate_path=gate)
    assert report['error']=='HTTP 429'
    now[0]+=31
    report=run_source.sync_page(None,None,None,tmp_path/'live','2026-09-05T00:00:00Z',rate_path=gate)
    assert report['retry_at']==1151 and len(calls)==2
    assert json.loads((tmp_path/'history/cursor.json').read_text())['cursor'] is None


def test_coordinator_retains_live_cursor_and_advances_both_historical_phases(tmp_path, network):
    now,calls,responses=network
    live=tmp_path/'live';history=tmp_path/'history';live.mkdir()
    old={'start':'2026-09-07T01:00:00Z','end':'2026-09-07T01:05:00Z',
         'cursor':None,'next_request_at':1000,'page_number':88,'endpoint':run_source.ENDPOINT}
    run_source.atomic(live/'cursor.json',old)
    responses.extend([Response(),Response(),Response()])
    args=(None,None,None,live,'2026-09-05T00:00:00Z',history)
    assert source_backfill.sync_sources(*args)['source_stream']=='live'
    advanced=json.loads((live/'cursor.json').read_text())
    assert advanced['page_number']==89
    assert calls[0]['start']==[old['start']]
    now[0]+=31
    assert source_backfill.sync_sources(*args)['source_stream']=='recent-history'
    assert calls[1]['start']==['2026-08-29T00:00:00+00:00']
    assert calls[1]['end']==['2026-09-05T00:00:00+00:00']
    now[0]+=31
    assert source_backfill.sync_sources(*args)['source_stream']=='full-archive'
    assert calls[2]=={'limit':['1000']}
    assert json.loads((history/'plan.json').read_text())['state']=='history_complete'
    assert json.loads((live/'cursor.json').read_text())==advanced
    now[0]+=31
    assert source_backfill.sync_sources(*args)['reason']=='historical_scan_complete'
    assert len(calls)==3


def test_enable_history_honors_existing_live_backoff(tmp_path,network):
    _,calls,_=network
    live=tmp_path/'live';live.mkdir()
    run_source.atomic(live/'cursor.json',{'next_request_at':1400})
    r=source_backfill.sync_sources(None,None,None,live,'2026-09-05T00:00:00Z',tmp_path/'history')
    assert r['retry_at']==1400 and not calls
