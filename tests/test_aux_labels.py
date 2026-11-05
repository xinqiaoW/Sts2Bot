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


def test_parse_trace_metrics_waterfall_infinite_hp():
    # Early kill jumps the giant from 10 real HP to the 999999999 sentinel.
    # The sentinel must not be added as leftover damage; the killing blow and
    # the 6 damage dealt inside the sentinel phase still count.
    trace_obj = {
        'trainingObservation': {'playerDied': False, 'initialBuild': {'relics': []}},
        'execution': {
            'trace': [
                {
                    'turn': 1,
                    'deployment': {
                        'trace': [
                            {
                                'action': {'CardId': 'STRIKE_SILENT', 'CardStateKey': 'STRIKE_SILENT|energy=False:1|damage=20'},
                                'live': 'turn=1;block=0;energy=2;E0=1/WATERFALL_GIANT/-/10/30/0/ATK;AI0=ATK;H=STRIKE_SILENT/baselib=-,;D=;C=;X=;',
                            },
                            {
                                'action': {'CardId': 'STRIKE_SILENT', 'CardStateKey': 'STRIKE_SILENT|energy=False:1|damage=10'},
                                'live': 'turn=1;block=0;energy=1;E0=1/WATERFALL_GIANT/-/999999999/999999999/0/ATK;AI0=ATK;H=STRIKE_SILENT/baselib=-,;D=;C=;X=;',
                            },
                            {
                                'action': {'CardId': 'STRIKE_SILENT', 'CardStateKey': 'STRIKE_SILENT|energy=False:1|damage=6'},
                                'live': 'turn=1;block=0;energy=0;E0=1/WATERFALL_GIANT/-/999999993/999999999/0/ATK;AI0=ATK;H=STRIKE_SILENT/baselib=-,;D=;C=;X=;',
                            },
                        ]
                    },
                }
            ]
        },
        'finishedTurn': 1,
    }
    dmg, *_ = parse_trace_metrics(json.dumps(trace_obj))
    # 20 from the first hit (30 -> 10), 10 from the kill, 6 inside the sentinel phase.
    assert dmg == 36.0


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



def test_step_snapshots_encoding_and_targets():
    import torch
    from train.features import Vocabulary
    from train.models import build_torch_model
    from train.step_snapshots import (
        NUM_STEP_IMM_TARGETS,
        augment_vocab_for_steps,
        encode_live_step_tokens,
        extract_battle_step_samples,
    )

    from train.data import load_catalog
    vocab = Vocabulary.build(load_catalog(), [])
    orig_syms = list(vocab.spec['symbols'])
    exhaust_idx = augment_vocab_for_steps(vocab)
    assert exhaust_idx > 0
    assert vocab.spec['symbols'][:len(orig_syms)] == orig_syms

    trace_obj = {
        'trainingObservation': {
            'playerDied': False,
            'finalHp': 64,
            'initialBuild': {'relics': [{'id': 'RING_OF_THE_SNAKE'}]},
        },
        'execution': {
            'trace': [
                {
                    'turn': 1,
                    'deployment': {
                        'trace': [
                            {
                                'action': {'CardId': 'STRIKE_SILENT', 'CardStateKey': 'STRIKE_SILENT|energy=False:1|damage=6'},
                                'live': 'turn=1;hp=70;max_hp=70;block=0;energy=2;Y=1/1;P=0:DEXTERITY_POWER=1/1[];R=;E0=1/CORPSE_SLUG/0/18/24/0/WHIP_SLAP_MOVE;AI0=WHIP_SLAP_MOVE;H=DEFEND_SILENT+0/False:1/2/0/0/False/False/False/1/-:0/baselib=-,;D=STRIKE_SILENT+1/False:1/1/0/0/False/False/False/1/-:0/baselib=-,;C=STRIKE_SILENT+0/False:1/1/0/0/False/False/False/1/-:0/baselib=-,;X=;relicCounters=;',
                            },
                            {
                                'action': {'CardId': 'DEFEND_SILENT', 'CardStateKey': 'DEFEND_SILENT|energy=False:1|Block=6'},
                                'live': 'turn=1;hp=70;max_hp=70;block=6;energy=1;Y=1/2;P=0:DEXTERITY_POWER=1/1[];R=;E0=1/CORPSE_SLUG/0/18/24/0/WHIP_SLAP_MOVE;AI0=WHIP_SLAP_MOVE;H=;D=STRIKE_SILENT+1/False:1/1/0/0/False/False/False/1/-:0/baselib=-,;C=STRIKE_SILENT+0/False:1/1/0/0/False/False/False/1/-:0/baselib=-,DEFEND_SILENT+0/False:1/2/0/0/False/False/False/1/-:0/baselib=-,;X=;relicCounters=;',
                            },
                        ]
                    },
                },
                {
                    'turn': 2,
                    'deployment': {
                        'trace': [
                            {
                                'action': {'CardId': 'STRIKE_SILENT', 'CardStateKey': 'STRIKE_SILENT|energy=False:1|damage=18'},
                                'live': 'turn=2;hp=64;max_hp=70;block=0;energy=2;Y=1/1;P=;R=;H=;D=;C=;X=;',
                            }
                        ]
                    },
                },
            ]
        },
        'finishedTurn': 2,
    }

    samples = extract_battle_step_samples(
        json.dumps(trace_obj),
        'OVERGROWTH',
        'CORPSE_SLUGS_WEAK',
        1.0,
        vocab.symbol_index,
        np.zeros(9, dtype=np.float32),
        np.ones(9, dtype=np.float32),
        max_steps_per_battle=4,
    )
    assert len(samples) == 2
    syms, nums, y_norm, died_val, z_aux, imm_y, step_w = samples[0]
    assert syms.shape[1] == 6
    assert nums.shape[1] == 4
    assert 0.0 <= y_norm <= 1.0
    assert died_val == 0.0
    assert z_aux.shape == (9,)
    assert imm_y.shape == (NUM_STEP_IMM_TARGETS,)

    model = build_torch_model(
        'set_transformer',
        vocab,
        {'d_model': 32, 'num_heads': 4, 'n_enc': 1, 'role_priors': True, 'aux_supervision': True, 'step_supervision': True},
    )
    s_t = torch.from_numpy(syms[None].astype(np.int64))
    n_t = torch.from_numpy(nums[None])
    out, aux_pred, imm_pred = model(s_t, n_t, return_step=True)
    assert out.shape == (1, 2)
    assert aux_pred.shape == (1, 9)
    assert imm_pred.shape == (1, NUM_STEP_IMM_TARGETS)


def test_balanced_emb_and_live_vars():
    import torch
    from train.features import Vocabulary
    from train.models import build_torch_model
    from train.step_snapshots import augment_vocab_for_steps, encode_live_step_tokens

    vocab = Vocabulary({
        'sparse_encoding': 1, 'token_encoding': 1,
        'features': [], 'symbols': ['<pad>', '<unk>'],
        'max_tokens': 64, 'token_slots': 6, 'token_numerics': 4,
        'min_count': 1, 'legal_encoder': {'features': []},
    })
    augment_vocab_for_steps(vocab)
    live = (
        "turn=2;hp=65;max_hp=70;block=0;energy=4;stars=0;gold=93;"
        "E0=1/BOWLBUG_ROCK/first/13/49/0/HEADBUTT_MOVE;"
        "AI0=TOXIC_SPIT_MOVE,HEADBUTT_MOVE;MS0=-/1;"
        "H=PINPOINT+1/False:0/False:-1/0/False/False/False/True/False/SLITHER:1:0/-:0[Damage=19,]/private=-/baselib=-,"
        "STRIKE_SILENT+0/False:1/False:-1/0/False/False/False/True/False/-:0:0/-:0[Damage=6,]/private=-/baselib=-,"
        "STRIKE_SILENT+0/False:1/False:-1/0/False/False/False/True/False/-:0:0/-:0[Damage=6,]/private=-/baselib=-,;"
        "D=;C=;X=;Y=0/1;mirrorRelics=KUSARIGAMA/1;"
        "P=0:WEAK_POWER=1/0[DamageDecrease=0.75,],1:VULNERABLE_POWER=2/0[DamageIncrease=1.5,],"
    )
    syms, nums = encode_live_step_tokens(live, "HIVE", "BOWLBUGS_NORMAL", [{"id": "KUSARIGAMA"}], vocab.symbol_index)
    inv = {i: k for k, i in vocab.symbol_index.items()}
    # Check zero step_hash collisions on BOWLBUG_ROCK / HEADBUTT_MOVE / TOXIC_SPIT_MOVE
    all_names = [inv[int(x)] for row in syms for x in row if int(x) != 0]
    assert not any(n.startswith("step_hash:") for n in all_names), f"Unexpected step_hash in {all_names}"
    assert abs(float(nums[3, 0]) - 19.0 / 25.0) < 1e-4  # PINPOINT Damage=19
    assert abs(float(nums[6, 0]) - 0.1) < 1e-4  # KUSARIGAMA mirrorRelics=1

    model = build_torch_model("set_transformer", vocab, {
        "d_model": 64, "num_heads": 4, "n_enc": 2,
        "role_priors": True, "aux_supervision": True, "step_supervision": True,
        "modern_transformer": True, "balanced_emb": True,
    })
    st = torch.from_numpy(syms[None].astype("int64"))
    nt = torch.from_numpy(nums[None])
    emb_out = model.embed(st, nt)
    # The two STRIKE_SILENT tokens (indices 4 and 5) must have distinct embeddings
    assert not torch.allclose(emb_out[0, 4], emb_out[0, 5])
