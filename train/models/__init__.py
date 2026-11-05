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
    """Sum of symbol embeddings plus numeric and role-context branches."""

    def __init__(self, n_symbols, n_numerics, d_model, *, role_priors=None, exhaust_idx=-1, balanced_emb=False):
        super().__init__()
        self.symbols = nn.Embedding(n_symbols, d_model, padding_idx=PAD)
        self.exhaust_idx = int(exhaust_idx)
        self.balanced_emb = bool(balanced_emb)
        if self.balanced_emb:
            self.copy_emb = nn.Embedding(16, d_model)
            self.sym_ln = nn.LayerNorm(d_model)
            self.numerics = nn.Sequential(
                nn.Linear(n_numerics + 4, d_model),
                nn.SiLU(),
                nn.Linear(d_model, d_model),
            )
            self.num_ln = nn.LayerNorm(d_model)
            self.role_ln = nn.LayerNorm(d_model)
            self.branch_scale = nn.Parameter(torch.tensor([1.0, 0.75, 0.85], dtype=torch.float32))
        else:
            self.copy_emb = None
            self.sym_ln = None
            self.numerics = nn.Linear(n_numerics, d_model)
            self.num_ln = None
            self.role_ln = None
            self.branch_scale = None
        if role_priors is not None:
            from ..role_priors import CONTEXT_DIM
            table_u0, table_u1, upgrade1_idx = role_priors
            self.register_buffer('prior_u0', torch.as_tensor(table_u0, dtype=torch.float32), persistent=False)
            self.register_buffer('prior_u1', torch.as_tensor(table_u1, dtype=torch.float32), persistent=False)
            self.upgrade1_idx = int(upgrade1_idx)
            extra_copy_dim = 4 if self.balanced_emb else 0
            in_dim = int(self.prior_u0.shape[1]) + CONTEXT_DIM + extra_copy_dim
            self.role_mlp = nn.Sequential(
                nn.Linear(in_dim, d_model),
                nn.SiLU(),
                nn.Linear(d_model, d_model),
            )
        else:
            self.prior_u0 = None
            self.prior_u1 = None
            self.upgrade1_idx = -1
            self.role_mlp = None

    @staticmethod
    def compute_copy_features(symbols):
        B, T, _ = symbols.shape
        sym0 = symbols[:, :, 0]
        sym1 = symbols[:, :, 1]
        sym4 = symbols[:, :, 4]
        has_entity = (sym1 > 0)
        same_entity = (
            (sym0.unsqueeze(2) == sym0.unsqueeze(1))
            & (sym1.unsqueeze(2) == sym1.unsqueeze(1))
            & has_entity.unsqueeze(2)
            & has_entity.unsqueeze(1)
        )
        tril = torch.tril(torch.ones((T, T), device=symbols.device, dtype=torch.bool), diagonal=-1)
        copy_idx = (same_entity & tril).sum(dim=-1)
        copy_tot = same_entity.sum(dim=-1).clamp(min=1)
        same_zone = same_entity & (sym4.unsqueeze(2) == sym4.unsqueeze(1))
        zone_copy_idx = (same_zone & tril).sum(dim=-1)
        zone_copy_tot = same_zone.sum(dim=-1).clamp(min=1)
        has_ent_f = has_entity.float()
        copy_feats = torch.stack([
            has_ent_f * (copy_idx.float() + 1.0) / copy_tot.float(),
            has_ent_f * (copy_tot.float() / 5.0),
            has_ent_f * (zone_copy_idx.float() + 1.0) / zone_copy_tot.float(),
            (copy_tot > 1).float(),
        ], dim=-1)
        return copy_idx, has_ent_f.unsqueeze(-1), copy_feats

    def forward(self, symbols, numerics):
        if not self.balanced_emb:
            out = self.symbols(symbols).sum(dim=2) + self.numerics(numerics)
            if self.prior_u0 is not None:
                from ..role_priors import compute_token_context
                sym1 = symbols[:, :, 1]
                if self.upgrade1_idx >= 0:
                    is_up = (symbols[:, :, 2] == self.upgrade1_idx).unsqueeze(-1)
                    priors = torch.where(is_up, self.prior_u1[sym1], self.prior_u0[sym1])
                else:
                    priors = self.prior_u0[sym1]
                if self.exhaust_idx >= 0:
                    active_mask = (symbols[:, :, 4] != self.exhaust_idx).unsqueeze(-1)
                    ctx = compute_token_context(priors * active_mask)
                else:
                    ctx = compute_token_context(priors)
                out = out + self.role_mlp(torch.cat([priors, ctx], dim=-1))
            return out

        copy_idx, has_ent_3d, copy_feats = self.compute_copy_features(symbols)
        n_active = (symbols != PAD).sum(dim=2, keepdim=True).clamp(min=1).float()
        sym_raw = (self.symbols(symbols).sum(dim=2) + has_ent_3d * self.copy_emb(copy_idx.clamp(max=15))) / (n_active + has_ent_3d).sqrt()
        sym_e = self.sym_ln(sym_raw)
        num_e = self.num_ln(self.numerics(torch.cat([numerics, copy_feats], dim=-1)))
        out = self.branch_scale[0] * sym_e + self.branch_scale[1] * num_e
        if self.prior_u0 is not None:
            from ..role_priors import compute_token_context
            sym1 = symbols[:, :, 1]
            if self.upgrade1_idx >= 0:
                is_up = (symbols[:, :, 2] == self.upgrade1_idx).unsqueeze(-1)
                priors = torch.where(is_up, self.prior_u1[sym1], self.prior_u0[sym1])
            else:
                priors = self.prior_u0[sym1]
            if self.exhaust_idx >= 0:
                active_mask = (symbols[:, :, 4] != self.exhaust_idx).unsqueeze(-1)
                ctx = compute_token_context(priors * active_mask)
            else:
                ctx = compute_token_context(priors)
            role_e = self.role_ln(self.role_mlp(torch.cat([priors, ctx, copy_feats], dim=-1)))
            out = out + self.branch_scale[2] * role_e
        return out


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
        role_priors = None
        if hparams.get('role_priors', False):
            from ..role_priors import build_symbol_prior_tables
            role_priors = build_symbol_prior_tables(vocab.spec['symbols'])
        n_aux = 0
        if hparams.get('aux_supervision', False):
            from ..aux_labels import NUM_AUX_TARGETS
            n_aux = NUM_AUX_TARGETS
        n_step_imm = 0
        if hparams.get('step_supervision', False):
            from ..step_snapshots import NUM_STEP_IMM_TARGETS
            n_step_imm = NUM_STEP_IMM_TARGETS
        exhaust_idx = vocab.symbol_index.get('zone:exhaust', -1)
        return SetRegressor(n_symbols=vocab.n_symbols, n_numerics=vocab.spec['token_numerics'],
                            d_model=hparams.get('d_model', 128), num_heads=hparams.get('num_heads', 4),
                            num_inds=hparams.get('num_inds', 0), n_enc=hparams.get('n_enc', 2),
                            ln=hparams.get('ln', True), dropout=hparams.get('dropout', 0.0),
                            role_priors=role_priors, n_aux=n_aux,
                            exhaust_idx=exhaust_idx, n_step_imm=n_step_imm,
                            modern_transformer=hparams.get('modern_transformer', False),
                            ffn_mult=hparams.get('ffn_mult', 4),
                            num_seeds=hparams.get('num_seeds', 4),
                            balanced_emb=hparams.get('balanced_emb', False))
    raise ValueError(f'Unknown torch model: {name}')
