import json
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from train.aux_labels import (
    AUX_COLUMNS,
    NUM_AUX_TARGETS,
    parse_trace_metrics,
    _worker_scan_range,
    build_snapshot_aux_parquet,
)


def test_parse_trace_metrics_valid_trace():
    trace_obj = {
        'trainingObservation': {'playerDied': False, 'initialBuild': {'relics': []}},
        'execution': {
            'trace': [
                {
                    'turn': 1,
                    'deployment': {
                        'trace': [
                            {
                                'action': {'CardId': 'STRIKE_SILENT', 'CardStateKey': 'STRIKE_SILENT|energy=False:1|damage=6'},
                                'live': 'turn=1;block=0;energy=2;E0=1/SLUG/-/24/30/0/ATK;AI0=ATK;H=DEFEND_SILENT/baselib=-,;D=;C=;X=;',
                            },
                            {
                                'action': {'CardId': 'DEFEND_SILENT', 'CardStateKey': 'DEFEND_SILENT|energy=False:1|Block=5'},
                                'live': 'turn=1;block=5;energy=1;E0=1/SLUG/-/18/30/0/ATK;AI0=ATK;H=;D=;C=;X=;',
                            },
                        ]
                    },
                }
            ]
        },
        'finishedTurn': 1,
    }
    raw_str = json.dumps(trace_obj)
    res = parse_trace_metrics(raw_str)
    assert res is not None
    assert len(res) == 8
    dmg_mean, dmg_stab, blk_mean, blk_stab, e_gen, e_used, draw, cards = res
    assert dmg_mean > 0
    assert blk_mean == 5.0
    assert cards == 2.0


def test_parse_trace_metrics_invalid():
    assert parse_trace_metrics('not a json') is None
    assert parse_trace_metrics('{}') is None
    assert parse_trace_metrics(json.dumps({'trainingObservation': {}})) is None


def test_worker_scan_range(tmp_path):
    db_path = tmp_path / 'test.sqlite'
    con = sqlite3.connect(db_path)
    con.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT, result TEXT)')
    trace_obj = {
        'trainingObservation': {'playerDied': False},
        'execution': {'trace': [{'turn': 1, 'deployment': {'trace': []}}]},
        'finishedTurn': 1,
    }
    con.execute('INSERT INTO jobs (id, status, result) VALUES (?, ?, ?)', ('job-1', 'complete', json.dumps(trace_obj)))
    con.execute('INSERT INTO jobs (id, status, result) VALUES (?, ?, ?)', ('job-2', 'failed', json.dumps(trace_obj)))
    con.commit()
    con.close()

    # Test 4-tuple
    ids, vals = _worker_scan_range((str(db_path), 1, 2, False))
    assert ids == ['job-1']
    assert vals.shape == (1, 8)

    # Test 5-tuple with chunk_idx
    chunk_idx, ids5, vals5 = _worker_scan_range((42, str(db_path), 1, 2, False))
    assert chunk_idx == 42
    assert ids5 == ['job-1']
    assert vals5.shape == (1, 8)


def test_build_snapshot_aux_parquet_with_checkpoint_resume(tmp_path):
    snapshot_dir = tmp_path / 'snapshot'
    snapshot_dir.mkdir()

    # Create dummy database
    db_path = tmp_path / 'sim.sqlite'
    con = sqlite3.connect(db_path)
    con.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT, result TEXT)')
    job_ids = [f'sim-job-{i}' for i in range(10)]
    for jid in job_ids:
        trace_obj = {
            'trainingObservation': {'playerDied': False},
            'execution': {
                'trace': [
                    {
                        'turn': 1,
                        'deployment': {
                            'trace': [
                                {
                                    'action': {'CardId': 'DEFEND_SILENT', 'CardStateKey': 'DEFEND_SILENT|energy=1|Block=5'},
                                    'live': 'health=70;block=5;energy=2;H=;',
                                }
                            ]
                        },
                    }
                ]
            },
            'finishedTurn': 1,
        }
        con.execute('INSERT INTO jobs (id, status, result) VALUES (?, ?, ?)', (jid, 'complete', json.dumps(trace_obj)))
    con.commit()
    con.close()

    # Manifest and battles
    manifest = {
        'sources': [
            {'name': 'sim-test', 'kind': 'real', 'db': str(db_path)},
            {'name': 'native-test', 'kind': 'real', 'db': 'none.sqlite'},
        ]
    }
    (snapshot_dir / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    battles_data = {
        'job_id': job_ids + ['native-job-1'],
        'source': ['sim-test'] * 10 + ['native-test'],
        'finished_turn': [1] * 11,
    }
    pq.write_table(pa.table(battles_data), snapshot_dir / 'battles.parquet')

    checkpoint_dir = snapshot_dir / '.aux_checkpoints'

    # Run extraction
    out_path = build_snapshot_aux_parquet(
        snapshot_dir,
        workers=2,
        checkpoint_dir=checkpoint_dir,
        resume=True,
    )
    assert out_path.exists()

    df = pq.read_table(out_path).to_pandas()
    assert len(df) == 11
    assert 'has_trace' in df.columns
    assert df['has_trace'].sum() == 10  # 10 sim jobs had trace, 1 native did not
    for col in AUX_COLUMNS:
        assert col in df.columns
        assert not np.isnan(df[col][:10]).any()
        assert np.isnan(df[col][10])

    # Check that source parquet was cached in checkpoint_dir
    src_parquet = checkpoint_dir / 'sim-test.parquet'
    assert src_parquet.exists()

    # Now remove out_path, but keep checkpoint_dir, and test resuming
    out_path.unlink()
    out_path2 = build_snapshot_aux_parquet(
        snapshot_dir,
        workers=2,
        checkpoint_dir=checkpoint_dir,
        resume=True,
    )
    assert out_path2.exists()
    df2 = pq.read_table(out_path2).to_pandas()
    assert df2['has_trace'].sum() == 10


def test_chunk_level_checkpoint_resume(tmp_path):
    snapshot_dir = tmp_path / 'snapshot'
    snapshot_dir.mkdir()

    db_path = tmp_path / 'sim2.sqlite'
    con = sqlite3.connect(db_path)
    con.execute('CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT, result TEXT)')
    job_ids = [f'sim-job2-{i}' for i in range(20)]
    for jid in job_ids:
        trace_obj = {
            'trainingObservation': {'playerDied': False},
            'execution': {
                'trace': [
                    {
                        'turn': 1,
                        'deployment': {
                            'trace': [
                                {
                                    'action': {'CardId': 'DEFEND_SILENT', 'CardStateKey': 'DEFEND_SILENT|energy=False:1|Block=5'},
                                    'live': 'turn=1;block=5;energy=2;H=;',
                                }
                            ]
                        },
                    }
                ]
            },
            'finishedTurn': 1,
        }
        con.execute('INSERT INTO jobs (id, status, result) VALUES (?, ?, ?)', (jid, 'complete', json.dumps(trace_obj)))
    con.commit()
    con.close()

    manifest = {'sources': [{'name': 'sim-chunk-test', 'kind': 'real', 'db': str(db_path)}]}
    (snapshot_dir / 'manifest.json').write_text(json.dumps(manifest), encoding='utf-8')

    battles_data = {
        'job_id': job_ids,
        'source': ['sim-chunk-test'] * 20,
        'finished_turn': [1] * 20,
    }
    pq.write_table(pa.table(battles_data), snapshot_dir / 'battles.parquet')

    checkpoint_dir = snapshot_dir / '.aux_checkpoints'
    chunk_dir = checkpoint_dir / 'sim-chunk-test'
    chunk_dir.mkdir(parents=True, exist_ok=True)

    # Pre-populate chunk 0 manually to simulate a partial run
    pre_table = pa.Table.from_arrays(
        [
            pa.array(['sim-job2-0'], type=pa.string()),
            *[pa.array([1.0], type=pa.float32()) for _ in AUX_COLUMNS],
        ],
        names=['job_id', *AUX_COLUMNS],
    )
    pq.write_table(pre_table, chunk_dir / 'chunk_00000.parquet')

    # Run extraction
    out_path = build_snapshot_aux_parquet(
        snapshot_dir,
        workers=2,
        checkpoint_dir=checkpoint_dir,
        resume=True,
    )
    assert out_path.exists()
    df = pq.read_table(out_path).to_pandas()
    assert len(df) == 20
    # The pre-populated chunk 0 had 1.0 for all columns
    row0 = df[df['job_id'] == 'sim-job2-0'].iloc[0]
    assert row0['dmg_per_turn'] == 1.0

