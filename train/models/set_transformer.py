"""Set Transformer blocks (Lee et al., ICML 2019) + Modern Pre-LN Entity Transformer.

``MAB``, ``SAB``, ``ISAB`` and ``PMA`` follow the official implementation
(https://github.com/juho-lee/set_transformer, ``modules.py``, MIT license) for
backward compatibility with earlier checkpoints.

When ``modern_transformer=True``, ``SetRegressor`` uses standard Pre-LN
Multi-Head Attention with output projection ``W_O`` (via PyTorch
``scaled_dot_product_attention``), 2-layer expanded GELU FFN
(``d_model -> ffn_mult * d_model -> d_model``), and multi-seed cross-attention
readout pooling (``num_seeds`` learned queries).
"""
from __future__ import annotations

import math

import torch
from torch import nn
import torch.nn.functional as F

from . import TokenEmbedding
from ..features import PAD


class MAB(nn.Module):
    def __init__(self, dim_Q, dim_K, dim_V, num_heads, ln=False):
        super().__init__()
        self.dim_V = dim_V
        self.num_heads = num_heads
        self.fc_q = nn.Linear(dim_Q, dim_V)
        self.fc_k = nn.Linear(dim_K, dim_V)
        self.fc_v = nn.Linear(dim_K, dim_V)
        if ln:
            self.ln0 = nn.LayerNorm(dim_V)
            self.ln1 = nn.LayerNorm(dim_V)
        self.fc_o = nn.Linear(dim_V, dim_V)

    def forward(self, Q, K, mask=None):
        Q = self.fc_q(Q)
        K, V = self.fc_k(K), self.fc_v(K)
        dim_split = self.dim_V // self.num_heads
        Q_ = torch.cat(Q.split(dim_split, 2), 0)
        K_ = torch.cat(K.split(dim_split, 2), 0)
        V_ = torch.cat(V.split(dim_split, 2), 0)
        logits = Q_.bmm(K_.transpose(1, 2)) / math.sqrt(self.dim_V)
        if mask is not None:
            key_mask = mask.repeat(self.num_heads, 1).unsqueeze(1)
            logits = logits.masked_fill(~key_mask, float('-inf'))
        A = torch.softmax(logits, 2)
        O = torch.cat((Q_ + A.bmm(V_)).split(Q.size(0), 0), 2)
        O = O if getattr(self, 'ln0', None) is None else self.ln0(O)
        O = O + F.relu(self.fc_o(O))
        O = O if getattr(self, 'ln1', None) is None else self.ln1(O)
        return O


class SAB(nn.Module):
    def __init__(self, dim_in, dim_out, num_heads, ln=False):
        super().__init__()
        self.mab = MAB(dim_in, dim_in, dim_out, num_heads, ln=ln)

    def forward(self, X, mask=None):
        return self.mab(X, X, mask=mask)


class ISAB(nn.Module):
    def __init__(self, dim_in, dim_out, num_heads, num_inds, ln=False):
        super().__init__()
        self.I = nn.Parameter(torch.Tensor(1, num_inds, dim_out))
        nn.init.xavier_uniform_(self.I)
        self.mab0 = MAB(dim_out, dim_in, dim_out, num_heads, ln=ln)
        self.mab1 = MAB(dim_in, dim_out, dim_out, num_heads, ln=ln)

    def forward(self, X, mask=None):
        H = self.mab0(self.I.repeat(X.size(0), 1, 1), X, mask=mask)
        return self.mab1(X, H)


class PMA(nn.Module):
    def __init__(self, dim, num_heads, num_seeds, ln=False):
        super().__init__()
        self.S = nn.Parameter(torch.Tensor(1, num_seeds, dim))
        nn.init.xavier_uniform_(self.S)
        self.mab = MAB(dim, dim, dim, num_heads, ln=ln)

    def forward(self, X, mask=None):
        return self.mab(self.S.repeat(X.size(0), 1, 1), X, mask=mask)


class ModernMHA(nn.Module):
    """Standard Multi-Head Attention with Q/K/V projections, W_O output projection, and SDPA."""

    def __init__(self, d_model: int, num_heads: int, dropout: float = 0.0):
        super().__init__()
        assert d_model % num_heads == 0, 'd_model must be divisible by num_heads'
        self.d_model = d_model
        self.num_heads = num_heads
        self.head_dim = d_model // num_heads
        self.dropout = dropout
        self.q_proj = nn.Linear(d_model, d_model)
        self.k_proj = nn.Linear(d_model, d_model)
        self.v_proj = nn.Linear(d_model, d_model)
        self.out_proj = nn.Linear(d_model, d_model)

    def forward(self, q: torch.Tensor, kv: torch.Tensor, key_mask: torch.Tensor | None = None) -> torch.Tensor:
        B, Lq, D = q.shape
        Lk = kv.shape[1]
        H, Dh = self.num_heads, self.head_dim
        Q = self.q_proj(q).view(B, Lq, H, Dh).transpose(1, 2)
        K = self.k_proj(kv).view(B, Lk, H, Dh).transpose(1, 2)
        V = self.v_proj(kv).view(B, Lk, H, Dh).transpose(1, 2)
        attn_mask = None
        if key_mask is not None:
            # key_mask: (B, Lk) bool, True for valid tokens
            attn_mask = key_mask[:, None, None, :]
        drop_p = self.dropout if self.training else 0.0
        out = F.scaled_dot_product_attention(Q, K, V, attn_mask=attn_mask, dropout_p=drop_p)
        out = out.transpose(1, 2).contiguous().view(B, Lq, D)
        return self.out_proj(out)


class ModernTransformerBlock(nn.Module):
    """Pre-LN Transformer Encoder block with 2-layer expanded GELU FFN."""

    def __init__(self, d_model: int, num_heads: int, ffn_mult: int = 4, dropout: float = 0.0):
        super().__init__()
        self.ln1 = nn.LayerNorm(d_model)
        self.attn = ModernMHA(d_model, num_heads, dropout=dropout)
        self.drop1 = nn.Dropout(dropout)
        self.ln2 = nn.LayerNorm(d_model)
        d_ff = d_model * ffn_mult
        self.ffn = nn.Sequential(
            nn.Linear(d_model, d_ff),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_ff, d_model),
        )
        self.drop2 = nn.Dropout(dropout)

    def forward(self, x: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
        h = self.ln1(x)
        x = x + self.drop1(self.attn(h, h, key_mask=mask))
        x = x + self.drop2(self.ffn(self.ln2(x)))
        return x


class ModernMultiSeedReadout(nn.Module):
    """Multi-query Cross-Attention pooling followed by seed interaction and fusion."""

    def __init__(self, d_model: int, num_heads: int, num_seeds: int = 4, ffn_mult: int = 4, dropout: float = 0.0):
        super().__init__()
        self.num_seeds = num_seeds
        self.seeds = nn.Parameter(torch.randn(1, num_seeds, d_model) * 0.02)
        self.ln_q = nn.LayerNorm(d_model)
        self.ln_kv = nn.LayerNorm(d_model)
        self.cross_attn = ModernMHA(d_model, num_heads, dropout=dropout)
        self.drop = nn.Dropout(dropout)
        self.ln_ff = nn.LayerNorm(d_model)
        d_ff = d_model * ffn_mult
        self.ffn = nn.Sequential(
            nn.Linear(d_model, d_ff),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(d_ff, d_model),
        )
        self.seed_block = ModernTransformerBlock(d_model, num_heads, ffn_mult=ffn_mult, dropout=dropout)
        self.fuse = nn.Sequential(
            nn.LayerNorm(num_seeds * d_model),
            nn.Linear(num_seeds * d_model, d_model),
            nn.GELU(),
            nn.LayerNorm(d_model),
        )

    def forward(self, x: torch.Tensor, mask: torch.Tensor | None = None) -> torch.Tensor:
        B = x.size(0)
        q = self.seeds.expand(B, -1, -1)
        q = q + self.drop(self.cross_attn(self.ln_q(q), self.ln_kv(x), key_mask=mask))
        q = q + self.drop(self.ffn(self.ln_ff(q)))
        q = self.seed_block(q, mask=None)
        return self.fuse(q.reshape(B, -1))


class SetRegressor(nn.Module):
    """Set/Entity Transformer over ``(symbols, numerics)`` tokens -> ``(B, 2)``."""

    def __init__(
        self,
        n_symbols,
        n_numerics,
        d_model=128,
        num_heads=4,
        num_inds=0,
        n_enc=2,
        ln=True,
        dropout=0.0,
        *,
        role_priors=None,
        n_aux=0,
        exhaust_idx=-1,
        n_step_imm=0,
        modern_transformer=False,
        ffn_mult=4,
        num_seeds=4,
        balanced_emb=False,
    ):
        super().__init__()
        self.modern_transformer = bool(modern_transformer)
        self.embed = TokenEmbedding(
            n_symbols, n_numerics, d_model,
            role_priors=role_priors, exhaust_idx=exhaust_idx, balanced_emb=balanced_emb
        )
        if self.modern_transformer:
            self.input_ln = nn.LayerNorm(d_model)
            self.enc = nn.ModuleList([
                ModernTransformerBlock(d_model, num_heads, ffn_mult=ffn_mult, dropout=dropout)
                for _ in range(n_enc)
            ])
            self.readout = ModernMultiSeedReadout(
                d_model, num_heads, num_seeds=num_seeds, ffn_mult=ffn_mult, dropout=dropout
            )
            self.pma = None
            self.dec = None
        else:
            self.input_ln = None
            self.readout = None
            block = (lambda: ISAB(d_model, d_model, num_heads, num_inds, ln=ln)) if num_inds > 0 else (lambda: SAB(d_model, d_model, num_heads, ln=ln))
            self.enc = nn.ModuleList([block() for _ in range(n_enc)])
            self.pma = PMA(d_model, num_heads, 1, ln=ln)
            self.dec = SAB(d_model, d_model, num_heads, ln=ln)
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(d_model, 2)
        self.aux_head = nn.Sequential(
            nn.Linear(d_model, d_model),
            nn.SiLU(),
            nn.Linear(d_model, n_aux),
        ) if n_aux > 0 else None
        if n_step_imm > 0:
            self.step_head_delta = nn.Sequential(
                nn.Linear(d_model, d_model),
                nn.SiLU(),
                nn.Linear(d_model, 2),
            )
            nn.init.zeros_(self.step_head_delta[-1].weight)
            nn.init.zeros_(self.step_head_delta[-1].bias)
            if n_aux > 0:
                self.step_aux_delta = nn.Sequential(
                    nn.Linear(d_model, d_model),
                    nn.SiLU(),
                    nn.Linear(d_model, n_aux),
                )
                nn.init.zeros_(self.step_aux_delta[-1].weight)
                nn.init.zeros_(self.step_aux_delta[-1].bias)
            else:
                self.step_aux_delta = None
            self.step_imm_head = nn.Sequential(
                nn.Linear(d_model, d_model),
                nn.SiLU(),
                nn.Linear(d_model, n_step_imm),
            )
        else:
            self.step_head_delta = None
            self.step_aux_delta = None
            self.step_imm_head = None

    def forward(self, symbols, numerics, *, return_aux=False, return_step=False):
        mask = symbols[:, :, 0] != PAD  # first slot is always the kind symbol
        X = self.embed(symbols, numerics)
        if self.modern_transformer:
            with torch.amp.autocast('cuda', dtype=torch.bfloat16, enabled=X.is_cuda):
                X = self.input_ln(X)
                for block in self.enc:
                    X = block(X, mask)
                h = self.dropout(self.readout(X, mask)).float()
        else:
            for block in self.enc:
                X = block(X, mask)
            Z = self.dec(self.pma(X, mask))
            h = self.dropout(Z[:, 0])
        out = self.head(h)
        if return_step:
            if self.step_head_delta is not None:
                out = out + self.step_head_delta(h)
            aux = None
            if self.aux_head is not None:
                aux = self.aux_head(h)
                if self.step_aux_delta is not None:
                    aux = aux + self.step_aux_delta(h)
            imm = self.step_imm_head(h) if self.step_imm_head is not None else None
            return out, aux, imm
        if return_aux and self.aux_head is not None:
            return out, self.aux_head(h)
        return out
