import json

import pytest

from tools.one_off.benchmark_seed_workers import summarize


def test_report_excludes_warmup_and_drain_and_counts_valid_completions(tmp_path):
    (tmp_path/'metrics').mkdir()
    (tmp_path/'stage.json').write_text(json.dumps({'workers':25,'measure_start':100,'measure_end':200}))
    events = [dict(event='finish', time=t, status='complete', target='TARGET', dataset='real', native_ms=1000)
              for t in (90,100,125,150,199,200,220)]
    events += [dict(event='native_failure', time=160, status='retry'),
               dict(event='db_begin', time=170, seconds=.2, success=True),
               dict(event='db_begin', time=171, seconds=2, success=False)]
    (tmp_path/'metrics/000.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in events))
    first={'time':100,'cpu':[100,0,10,890,0,0,0,0], 'available_gib':200,
           'swap_used_gib':2,'pids':1000,'disk':[0]*11,'backup_io':{}}
    second={**first,'time':200,'cpu':[200,0,20,1770,10,0,0,0], 'available_gib':180,'pids':1100}
    (tmp_path/'monitor.jsonl').write_text(json.dumps(first)+'\n'+json.dumps(second)+'\n')
    result=summarize(tmp_path)
    assert result['completed']==4 and result['completed_per_hour']==144
    assert result['failure_fraction']==pytest.approx(.2)
    assert result['db_begins_over_100ms']==2 and result['db_begins_over_1s']==1
    assert result['db_begins_failed']==1
    assert result['resources']['cpu_busy_percent']==11
    assert result['resources']['cpu_iowait_percent']==1
    assert result['resources']['available_gib_min']==180
