"""Input encodings for the expected-HP-loss models.

Two views of the same build/target input are produced:

* ``sparse_features`` — the exact feature keys and scalings of
  ``damage_model.encoding.Encoder.encode`` as a sparse ``{key: value}`` dict.
  The full legal key set still comes from ``Encoder.from_catalog``; the model
  vocabulary is the subset observed in the training split. Tabular models
  (repo MLP, LightGBM, rtdl MLP/ResNet, TabM) consume this view.
* ``tokens`` — one token per card, relic and target plus a global token, each
  a bag of categorical symbols and a small numeric vector. Set models
  (Set Transformer) consume this view.

Unknown catalog features raise, mirroring the collection encoder. Legal but
untrained symbols/features are reported so inference can flag extrapolation.
"""
from __future__ import annotations

from collections import Counter
import numpy as np
import scipy.sparse as sp

from damage_model.card_state import DEFAULTS
from damage_model.encoding import Encoder
from damage_model.schema import Build, canonical

SPARSE_ENCODING = 'card_upgrade_enchantment_saved_variants_v3'
TOKEN_ENCODING = 'set_tokens_v1'
TOKEN_SLOTS = 6      # categorical symbol slots per token
TOKEN_NUMERICS = 4   # numeric slots per token
PAD, UNK = 0, 1


def sparse_features(build: Build, target_id: str, max_hp: float) -> dict[str, float]:
    """Mirror of ``Encoder.encode`` producing only the non-zero entries."""
    out = Counter()
    out['deck_size'] += len(build.cards) / 45
    out['max_hp'] += max_hp / 100
    out['act'] += build.act / 3
    for card in build.cards:
        out[f'card:{card.id}:count'] += 1 / 5
        out[f'card:{card.id}:upgrades'] += card.upgrade / 5
        if card.id in DEFAULTS:
            prefix = f'saved:{card.id}:{card.upgrade}:{canonical(dict(card.persistent_state))}'
            out[prefix + ':count'] += 1 / 5
            if card.enchantment_id:
                out[prefix + ':' + card.enchantment_id + ':count'] += 1 / 5
                out[prefix + ':' + card.enchantment_id + ':amount'] += card.enchantment_amount / 10
                out[prefix + ':' + card.enchantment_id + ':amount_squared'] += (card.enchantment_amount / 10) ** 2
        if card.enchantment_id:
            prefix = f'enchanted:{card.id}:{card.upgrade}:{card.enchantment_id}'
            out[prefix + ':count'] += 1 / 5
            out[prefix + ':amount'] += card.enchantment_amount / 10
            out[prefix + ':amount_squared'] += (card.enchantment_amount / 10) ** 2
    for index, relic in enumerate(build.relics):
        out[f'relic:{relic.id}:present'] += 1
        out[f'relic:{relic.id}:order'] += (index + 1) / max(1, len(build.relics))
        for key, value in relic.state:
            out[f'relic:{relic.id}:{key}'] += float(value) / 10
    out['target:' + build.act_id + ':' + target_id] += 1
    return {k: float(v) for k, v in out.items() if v != 0}


def tokens(build: Build, target_id: str, max_hp: float):
    """Return ``[(symbols, numerics), ...]`` for one build/target input."""
    result = [(['kind:global'], [len(build.cards) / 45, max_hp / 100, build.act / 3, 1.0])]
    for card in build.cards:
        symbols = ['kind:card', f'card:{card.id}', f'upgrade:{card.upgrade}',
                   'ench:' + (card.enchantment_id or 'none')]
        if card.id in DEFAULTS:
            symbols.append(f'state:{card.id}:{canonical(dict(card.persistent_state))}')
        amount = card.enchantment_amount / 10
        result.append((symbols, [amount, amount * amount, 0.0, 0.0]))
    for index, relic in enumerate(build.relics):
        symbols = ['kind:relic', f'relic:{relic.id}'] + [f'counter:{relic.id}:{k}={v}' for k, v in relic.state]
        result.append((symbols, [0.0, 0.0, (index + 1) / max(1, len(build.relics)), 0.0]))
    result.append((['kind:target', f'target:{build.act_id}:{target_id}'], [0.0, 0.0, 0.0, 0.0]))
    for symbols, _ in result:
        if len(symbols) > TOKEN_SLOTS:
            raise ValueError('Token has more symbols than slots: ' + ','.join(symbols))
    return result


class Vocabulary:
    """Observed feature keys and token symbols, frozen at training time."""

    def __init__(self, spec):
        self.spec = spec
        self.feature_index = {k: i for i, k in enumerate(spec['features'])}
        self.symbol_index = {k: i for i, k in enumerate(spec['symbols'])}
        self.legal = Encoder(spec['legal_encoder']).positions

    @classmethod
    def build(cls, catalog, inputs, *, min_count=1):
        """``inputs`` yields ``(Build, target_id, max_hp)`` from the training split only."""
        legal = Encoder.from_catalog(catalog)
        feature_counts, symbol_counts = Counter(), Counter()
        max_tokens = 0
        for build, target_id, max_hp in inputs:
            features = sparse_features(build, target_id, max_hp)
            for key in features:
                if key not in legal.positions:
                    raise ValueError(f'Unknown model feature: {key}')
            feature_counts.update(features.keys())
            toks = tokens(build, target_id, max_hp)
            max_tokens = max(max_tokens, len(toks))
            for symbols, _ in toks:
                symbol_counts.update(symbols)
        features = sorted(k for k, n in feature_counts.items() if n >= min_count)
        symbols = ['<pad>', '<unk>'] + sorted(k for k, n in symbol_counts.items() if n >= min_count)
        return cls({'sparse_encoding': SPARSE_ENCODING, 'token_encoding': TOKEN_ENCODING,
                    'features': features, 'symbols': symbols, 'max_tokens': max_tokens,
                    'token_slots': TOKEN_SLOTS, 'token_numerics': TOKEN_NUMERICS,
                    'min_count': min_count, 'legal_encoder': legal.spec})

    @property
    def n_features(self):
        return len(self.feature_index)

    @property
    def n_symbols(self):
        return len(self.symbol_index)

    def encode_sparse(self, build, target_id, max_hp):
        """Return ``(indices, values, untrained_keys)``; unknown catalog keys raise."""
        indices, values, untrained = [], [], []
        for key, value in sparse_features(build, target_id, max_hp).items():
            if key not in self.legal:
                raise ValueError(f'Unknown model feature: {key}')
            position = self.feature_index.get(key)
            if position is None:
                untrained.append(key)
            else:
                indices.append(position)
                values.append(value)
        return np.asarray(indices, dtype=np.int32), np.asarray(values, dtype=np.float32), untrained

    def encode_tokens(self, build, target_id, max_hp):
        """Return ``(symbols[T, S], numerics[T, N], untrained_symbols)`` for one input."""
        toks = tokens(build, target_id, max_hp)
        symbols = np.zeros((len(toks), TOKEN_SLOTS), dtype=np.int32)
        numerics = np.zeros((len(toks), TOKEN_NUMERICS), dtype=np.float32)
        untrained = []
        for t, (syms, nums) in enumerate(toks):
            for s, symbol in enumerate(syms):
                index = self.symbol_index.get(symbol)
                if index is None:
                    untrained.append(symbol)
                    index = UNK
                symbols[t, s] = index
            numerics[t, :len(nums)] = nums
        return symbols, numerics, untrained


def encode_pairs(vocab: Vocabulary, pairs, progress=None):
    """Encode many ``(Build, target_id, max_hp)`` inputs into a CSR matrix and padded token tensors."""
    rows, cols, vals, token_parts = [], [], [], []
    n = len(pairs)
    untrained_features, untrained_symbols = Counter(), Counter()
    for i, (build, target_id, max_hp) in enumerate(pairs):
        idx, val, missing = vocab.encode_sparse(build, target_id, max_hp)
        untrained_features.update(missing)
        rows.append(np.full(len(idx), i, dtype=np.int32)); cols.append(idx); vals.append(val)
        sym, num, missing = vocab.encode_tokens(build, target_id, max_hp)
        untrained_symbols.update(missing)
        token_parts.append((sym, num))
        if progress and (i + 1) % 20000 == 0:
            progress(i + 1, n)
    matrix = sp.csr_matrix((np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
                           shape=(n, vocab.n_features), dtype=np.float32)
    symbols, numerics, lengths = pad_tokens(token_parts)
    return {'sparse': matrix, 'symbols': symbols, 'numerics': numerics, 'lengths': lengths,
            'untrained_features': dict(untrained_features), 'untrained_symbols': dict(untrained_symbols)}


def pad_tokens(parts, min_tokens=1):
    """Pad ``[(symbols[T_i, S], numerics[T_i, N]), ...]`` to a common length.

    Set models are permutation invariant and mask padding, so the padded length
    is just the longest input in the batch, not a trained constant.
    """
    n = len(parts)
    max_tokens = max([min_tokens] + [len(sym) for sym, _ in parts])
    symbols = np.zeros((n, max_tokens, TOKEN_SLOTS), dtype=np.int32)
    numerics = np.zeros((n, max_tokens, TOKEN_NUMERICS), dtype=np.float32)
    lengths = np.zeros(n, dtype=np.int32)
    for i, (sym, num) in enumerate(parts):
        symbols[i, :len(sym)] = sym; numerics[i, :len(num)] = num; lengths[i] = len(sym)
    return symbols, numerics, lengths
