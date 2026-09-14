"""Load a training snapshot into pair-level encodings and row-level labels."""
from __future__ import annotations

from collections import Counter
import gzip
import hashlib
import json
import os
from pathlib import Path
import pickle
import time

import numpy as np
import pyarrow.parquet as pq
import scipy.sparse as sp

from damage_model.catalog import Catalog
from damage_model.schema import Build

from . import ROOT
from .features import SPARSE_ENCODING, TOKEN_ENCODING, Vocabulary, encode_pairs

SPLITS = ('train', 'validation', 'test')


class Snapshot:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.manifest = json.loads((self.directory / 'manifest.json').read_text(encoding='utf-8'))
        with gzip.open(self.directory / 'builds.json.gz', 'rt', encoding='utf-8') as stream:
            records = json.load(stream)
        self.builds = {r['id']: r for r in records}
        self.targets = json.loads((self.directory / 'targets.json').read_text(encoding='utf-8'))
        self.battles = pq.read_table(self.directory / 'battles.parquet').to_pandas()

    def build(self, build_id) -> Build:
        return Build.from_dict(self.builds[build_id]['body'])


class Dataset:
    """Pair-level features plus row-level labels for one snapshot.

    ``pairs`` holds one entry per distinct (build, target). ``rows`` reference a
    pair by ``pair`` and carry the labels of one native battle. Rows are weighted
    by ``1 / rows_in_pair`` so unequal repeat counts do not change which
    build/target combinations dominate, as in ``damage_model.model.train``.
    """

    def __init__(self, snapshot: Snapshot, vocab: Vocabulary, pairs, encoded, rows):
        self.snapshot, self.vocab, self.pairs, self.encoded, self.rows = snapshot, vocab, pairs, encoded, rows

    @classmethod
    def load(cls, snapshot_dir, catalog: Catalog, *, min_count=1, cache=True, log=print):
        snapshot = Snapshot(snapshot_dir)
        battles = snapshot.battles
        if battles.empty:
            raise ValueError('Snapshot has no battles')
        pair_keys = battles[['build_id', 'target_id']].drop_duplicates().reset_index(drop=True)
        pair_index = {(b, t): i for i, (b, t) in enumerate(zip(pair_keys.build_id, pair_keys.target_id))}
        pairs = pair_keys.copy()
        pairs['act_id'] = [snapshot.builds[b]['body']['act_id'] for b in pairs.build_id]
        pairs['split'] = [snapshot.builds[b]['split'] for b in pairs.build_id]
        pairs['kind'] = [snapshot.builds[b]['kind'] for b in pairs.build_id]
        pairs['group'] = [snapshot.builds[b]['group'] for b in pairs.build_id]
        rows = battles.copy()
        rows['pair'] = [pair_index[(b, t)] for b, t in zip(rows.build_id, rows.target_id)]
        rows['y'] = rows.hp_loss.astype(np.float32) / rows.max_hp.astype(np.float32)
        rows['died'] = rows.died.astype(np.float32)
        counts = rows.groupby('pair').size()
        rows['weight'] = (1.0 / counts.reindex(rows.pair).to_numpy()).astype(np.float32)
        for split in SPLITS:
            if (pairs.split == split).sum() == 0:
                raise ValueError(f'Snapshot has no {split} pairs; refusing to train without held-out groups')
        # Vocabulary from the training split only, then encode every pair once.
        key = hashlib.sha256(json.dumps({'snapshot': snapshot.manifest['files'], 'min_count': min_count,
                                         'sparse': SPARSE_ENCODING, 'tokens': TOKEN_ENCODING,
                                         'game_sha256': catalog.raw['game_sha256']}, sort_keys=True).encode()).hexdigest()[:16]
        cache_path = snapshot.directory / 'features' / f'{key}.pkl'
        if cache and cache_path.exists():
            with cache_path.open('rb') as stream:
                vocab_spec, encoded = pickle.load(stream)
            vocab = Vocabulary(vocab_spec)
            log(json.dumps({'event': 'features_cached', 'path': str(cache_path), 'features': vocab.n_features, 'symbols': vocab.n_symbols}))
        else:
            started = time.time()
            max_hp = rows.groupby('pair').max_hp.first()
            def inputs(mask):
                for i in np.flatnonzero(mask):
                    yield snapshot.build(pairs.build_id[i]), pairs.target_id[i], float(max_hp[i])
            vocab = Vocabulary.build(catalog, inputs((pairs.split == 'train').to_numpy()), min_count=min_count)
            log(json.dumps({'event': 'vocabulary', 'features': vocab.n_features, 'symbols': vocab.n_symbols,
                            'max_tokens': vocab.spec['max_tokens'], 'elapsed_s': round(time.time() - started, 1)}))
            encoded = encode_pairs(vocab, list(inputs(np.ones(len(pairs), dtype=bool))),
                                   progress=lambda i, n: log(json.dumps({'event': 'encoding', 'pairs': i, 'of': n})))
            log(json.dumps({'event': 'encoded', 'pairs': len(pairs), 'nnz': int(encoded['sparse'].nnz),
                            'untrained_features_in_holdout': sum(encoded['untrained_features'].values()),
                            'untrained_symbols_in_holdout': sum(encoded['untrained_symbols'].values()),
                            'elapsed_s': round(time.time() - started, 1)}))
            if cache:
                # Concurrent trainers may encode the same snapshot; publish atomically.
                cache_path.parent.mkdir(parents=True, exist_ok=True)
                temporary = cache_path.with_suffix(f'.{os.getpid()}.tmp')
                with temporary.open('wb') as stream:
                    pickle.dump((vocab.spec, encoded), stream, protocol=pickle.HIGHEST_PROTOCOL)
                temporary.replace(cache_path)
        return cls(snapshot, vocab, pairs, encoded, rows)

    def split_rows(self, split):
        mask = self.pairs.split.to_numpy()[self.rows.pair.to_numpy()] == split
        return self.rows[mask]

    def row_matrix(self, rows) -> sp.csr_matrix:
        return self.encoded['sparse'][rows.pair.to_numpy()]

    def summary(self):
        out = {}
        for split in SPLITS:
            rows = self.split_rows(split)
            out[split] = {'rows': len(rows), 'pairs': int(rows.pair.nunique()), 'builds': int(rows.build_id.nunique()),
                          'groups': int(self.pairs.group[rows.pair.unique()].nunique()),
                          'by_kind': dict(Counter(rows.kind)), 'by_source': dict(Counter(rows.source)),
                          'mean_hp_loss': float(rows.hp_loss.mean()), 'death_rate': float(rows.died.mean())}
        return out


def noise_floor(rows):
    """Irreducible error estimates from repeated seeds of the same input.

    * ``within_pair_rmse_hp``: sqrt of the mean within-pair variance (unbiased),
      the row-level RMSE that even a perfect conditional-mean predictor incurs.
    * ``loo_seed_mean_mae_hp``: MAE of predicting one seed by the mean of the
      other seeds of the same pair, a strong but unfair reference.
    """
    grouped = rows.groupby('pair')
    hp = rows.hp_loss.to_numpy(dtype=np.float64)
    n = grouped.hp_loss.transform('size').to_numpy()
    total = grouped.hp_loss.transform('sum').to_numpy()
    multi = n > 1
    if not multi.any():
        return {'within_pair_rmse_hp': None, 'loo_seed_mean_mae_hp': None, 'multi_seed_rows': 0}
    loo = (total[multi] - hp[multi]) / (n[multi] - 1)
    variance = grouped.hp_loss.var(ddof=1).dropna()
    return {'within_pair_rmse_hp': float(np.sqrt(variance.mean())),
            'loo_seed_mean_mae_hp': float(np.abs(loo - hp[multi]).mean()),
            'multi_seed_rows': int(multi.sum()), 'pairs_with_multiple_seeds': int(len(variance))}


def load_catalog(catalog_path=None, config_path=None):
    return Catalog.load(catalog_path or ROOT / 'catalogs/game-0.111.0.raw.json',
                        config_path or ROOT / 'configs/real-runs-8s.json')
