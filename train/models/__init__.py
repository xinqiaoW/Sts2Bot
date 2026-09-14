"""Model zoo: adaptations of existing architectures, not new designs.

Every torch model maps one encoded input to a ``(..., 2)`` tensor whose last
dimension is ``[normalized expected HP loss, death logit]``. Ensembles (TabM)
return ``(batch, k, 2)``; the trainer averages members for prediction.

Sources:

* ``repo_mlp``         — ``damage_model.model.DamageNet`` from this repository.
* ``rtdl_mlp``/``rtdl_resnet`` — ``rtdl_revisiting_models`` (Gorishniy et al.,
  "Revisiting Deep Learning Models for Tabular Data", NeurIPS 2021).
* ``tabm``             — ``tabm`` package (Gorishniy et al., "TabM", ICLR 2025).
* ``set_transformer``  — Lee et al., "Set Transformer", ICML 2019; modules
  vendored from the official implementation with a key-padding mask added.
* ``lightgbm``         — Ke et al., LightGBM (NeurIPS 2017), two boosters.
"""
from __future__ import annotations

import torch
from torch import nn

from ..features import PAD

SPARSE_MODELS = ('repo_mlp', 'rtdl_mlp', 'rtdl_resnet', 'tabm')
TOKEN_MODELS = ('set_transformer',)
TORCH_MODELS = SPARSE_MODELS + TOKEN_MODELS
BOOSTER_MODELS = ('lightgbm',)
ALL_MODELS = TORCH_MODELS + BOOSTER_MODELS


def input_kind(model_name):
    if model_name in SPARSE_MODELS or model_name in BOOSTER_MODELS:
        return 'sparse'
    if model_name in TOKEN_MODELS:
        return 'tokens'
    raise ValueError(f'Unknown model: {model_name}')


class RepoMLP(nn.Module):
    """``DamageNet`` from ``damage_model.model`` with a stacked ``(B, 2)`` output."""

    def __init__(self, d_in, hidden=128):
        super().__init__()
        from damage_model.model import DamageNet
        self.net = DamageNet(d_in, hidden)

    def forward(self, x):
        mean, death = self.net(x)
        return torch.stack([mean, death], dim=-1)


class TokenEmbedding(nn.Module):
    """Sum of symbol embeddings plus a linear map of the numeric slots."""

    def __init__(self, n_symbols, n_numerics, d_model):
        super().__init__()
        self.symbols = nn.Embedding(n_symbols, d_model, padding_idx=PAD)
        self.numerics = nn.Linear(n_numerics, d_model)

    def forward(self, symbols, numerics):
        return self.symbols(symbols).sum(dim=2) + self.numerics(numerics)


def build_torch_model(name, vocab, hparams) -> nn.Module:
    if name == 'repo_mlp':
        return RepoMLP(vocab.n_features, hparams.get('hidden', 128))
    if name == 'rtdl_mlp':
        from rtdl_revisiting_models import MLP
        return MLP(d_in=vocab.n_features, d_out=2, n_blocks=hparams.get('n_blocks', 3),
                   d_block=hparams.get('d_block', 512), dropout=hparams.get('dropout', 0.1))
    if name == 'rtdl_resnet':
        from rtdl_revisiting_models import ResNet
        return ResNet(d_in=vocab.n_features, d_out=2, n_blocks=hparams.get('n_blocks', 3),
                      d_block=hparams.get('d_block', 256), d_hidden_multiplier=hparams.get('d_hidden_multiplier', 2.0),
                      dropout1=hparams.get('dropout1', 0.15), dropout2=hparams.get('dropout2', 0.0))
    if name == 'tabm':
        from tabm import TabM
        return TabM.make(n_num_features=vocab.n_features, cat_cardinalities=None, d_out=2,
                         n_blocks=hparams.get('n_blocks', 3), d_block=hparams.get('d_block', 512),
                         dropout=hparams.get('dropout', 0.1), k=hparams.get('k', 32),
                         arch_type=hparams.get('arch_type', 'tabm'))
    if name == 'set_transformer':
        from .set_transformer import SetRegressor
        return SetRegressor(n_symbols=vocab.n_symbols, n_numerics=vocab.spec['token_numerics'],
                            d_model=hparams.get('d_model', 128), num_heads=hparams.get('num_heads', 4),
                            num_inds=hparams.get('num_inds', 0), n_enc=hparams.get('n_enc', 2),
                            ln=hparams.get('ln', True), dropout=hparams.get('dropout', 0.0))
    raise ValueError(f'Unknown torch model: {name}')
