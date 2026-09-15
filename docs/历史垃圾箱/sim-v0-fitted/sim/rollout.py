"""Batch rollouts of the abstract simulator with a fixed policy.

Returns floor records in the same format as :func:`sim.history.floor_records`
(plus a ``combat`` field with the oracle's diagnostics), so human and simulated
trajectories can be summarised by the same code.
"""
from __future__ import annotations

import json
import time

from .env import RunEnv, VecRunEnv
from .oracle import CombatOracle


def rollout(tables, catalog, oracle: CombatOracle, policy, episodes, *, seed=0, batch=256, log=print):
    records, summary = [], {'episodes': 0, 'wins': 0, 'floors': 0, 'fights': 0, 'seconds': 0.0}
    started = time.time()
    for start in range(0, episodes, batch):
        n = min(batch, episodes - start)
        envs = [RunEnv(tables, catalog, None, seed=seed + start + i) for i in range(n)]
        VecRunEnv(envs, oracle).run(policy)
        for i, env in enumerate(envs):
            run_id = f'sim-{seed + start + i}'
            for record in env.history:
                record['run'] = run_id
            records.extend(env.history)
            summary['episodes'] += 1
            summary['wins'] += int(env.won)
            summary['floors'] += env.total_floor
            summary['fights'] += sum(1 for h in env.history if h['combat'])
        if log:
            log(json.dumps({'event': 'rollout', 'oracle': oracle.name, 'policy': policy.name, 'episodes': summary['episodes'],
                            'win_rate': round(summary['wins'] / summary['episodes'], 4),
                            'mean_floors': round(summary['floors'] / summary['episodes'], 2),
                            'elapsed_s': round(time.time() - started, 1)}))
    summary['seconds'] = time.time() - started
    return records, summary
