"""Evaluation metrics shared by every model.

Predictions are normalized (HP loss / max HP). Metrics are reported in HP by
multiplying with each row's ``max_hp``. Row metrics weight each row by
``1 / rows_in_pair``; pair metrics compare the prediction with the mean over
all seeds of the same (build, target) and so exclude most of the irreducible
combat randomness.
"""
from __future__ import annotations

import numpy as np
from sklearn.metrics import roc_auc_score

from .data import noise_floor


def _weighted(values, weights):
    return float((values * weights).sum() / weights.sum())


def evaluate(rows, pred_mean, pred_death, *, groupers=('kind', 'act_id', 'source')):
    """``rows`` is a Dataset row frame; ``pred_*`` are aligned 1-D arrays."""
    rows = rows.reset_index(drop=True)
    pred_mean = np.asarray(pred_mean, dtype=np.float64)
    pred_death = np.asarray(pred_death, dtype=np.float64)
    result = {'overall': _block(rows, pred_mean, pred_death)}
    for column in groupers:
        if column in rows and rows[column].nunique() > 1:
            result['by_' + column] = {str(value): _block(rows[rows[column] == value], pred_mean[(rows[column] == value).to_numpy()],
                                                          pred_death[(rows[column] == value).to_numpy()])
                                      for value in sorted(rows[column].unique())}
    return result


def _block(rows, pred_mean, pred_death):
    max_hp = rows.max_hp.to_numpy(dtype=np.float64)
    hp_pred = np.clip(pred_mean, 0, 1) * max_hp
    hp_true = rows.hp_loss.to_numpy(dtype=np.float64)
    weights = rows.weight.to_numpy(dtype=np.float64)
    died = rows.died.to_numpy(dtype=np.float64)
    error = hp_pred - hp_true
    out = {'rows': int(len(rows)), 'pairs': int(rows.pair.nunique()), 'builds': int(rows.build_id.nunique()),
           'row_mae_hp': _weighted(np.abs(error), weights),
           'row_rmse_hp': float(np.sqrt(_weighted(error ** 2, weights))),
           'row_bias_hp': _weighted(error, weights),
           'mean_true_hp_loss': _weighted(hp_true, weights),
           'death_rate': _weighted(died, weights),
           'death_brier': _weighted((np.clip(pred_death, 0, 1) - died) ** 2, weights)}
    if 0 < died.sum() < len(died):
        out['death_auc'] = float(roc_auc_score(died, pred_death, sample_weight=weights))
    else:
        out['death_auc'] = None
    frame = rows[['pair']].copy()
    frame['pred'] = hp_pred
    frame['true'] = hp_true
    pair = frame.groupby('pair').agg(pred=('pred', 'mean'), true=('true', 'mean'), n=('true', 'size'))
    pair_error = (pair.pred - pair.true).to_numpy()
    out['pair_mae_hp'] = float(np.abs(pair_error).mean())
    out['pair_rmse_hp'] = float(np.sqrt((pair_error ** 2).mean()))
    variance = float(((pair.true - pair.true.mean()) ** 2).mean())
    out['pair_r2'] = float(1 - (pair_error ** 2).mean() / variance) if variance > 0 else None
    out['pair_mean_true_hp_loss'] = float(pair.true.mean())
    out['pair_std_true_hp_loss'] = float(np.sqrt(variance))
    out.update({'floor_' + k: v for k, v in noise_floor(rows).items()})
    return out


def summarize(metrics):
    """Short line used in logs: test pair MAE / row MAE / death AUC."""
    o = metrics['overall']
    return f"pair_mae={o['pair_mae_hp']:.3f} row_mae={o['row_mae_hp']:.3f} row_rmse={o['row_rmse_hp']:.3f} r2={o['pair_r2']:.3f} brier={o['death_brier']:.4f} auc={o['death_auc']}"
