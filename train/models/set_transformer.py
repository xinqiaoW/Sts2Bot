"""Set Transformer blocks (Lee et al., ICML 2019).

``MAB``, ``SAB``, ``ISAB`` and ``PMA`` follow the official implementation
(https://github.com/juho-lee/set_transformer, ``modules.py``, MIT license).
The only change is an optional key-padding ``mask`` so variable-size decks and
relic inventories can be batched; masked keys receive zero attention weight.
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
            # mask: (B, n_keys) True for real keys. Repeat per head along the batch axis.
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
        return self.mab(X, X, mask)


class ISAB(nn.Module):
    def __init__(self, dim_in, dim_out, num_heads, num_inds, ln=False):
        super().__init__()
        self.I = nn.Parameter(torch.Tensor(1, num_inds, dim_out))
        nn.init.xavier_uniform_(self.I)
        self.mab0 = MAB(dim_out, dim_in, dim_out, num_heads, ln=ln)
        self.mab1 = MAB(dim_in, dim_out, dim_out, num_heads, ln=ln)

    def forward(self, X, mask=None):
        H = self.mab0(self.I.repeat(X.size(0), 1, 1), X, mask)
        return self.mab1(X, H)


class PMA(nn.Module):
    def __init__(self, dim, num_heads, num_seeds, ln=False):
        super().__init__()
        self.S = nn.Parameter(torch.Tensor(1, num_seeds, dim))
        nn.init.xavier_uniform_(self.S)
        self.mab = MAB(dim, dim, dim, num_heads, ln=ln)

    def forward(self, X, mask=None):
        return self.mab(self.S.repeat(X.size(0), 1, 1), X, mask)


class SetRegressor(nn.Module):
    """Set Transformer encoder/decoder over card, relic, target and global tokens.

    Encoder: ``n_enc`` SAB blocks (or ISAB when ``num_inds > 0``). Decoder: PMA
    with one seed, one SAB, then a linear head, as in the official ``SetTransformer``.
    """

    def __init__(self, n_symbols, n_numerics, d_model=128, num_heads=4, num_inds=0, n_enc=2, ln=True, dropout=0.0):
        super().__init__()
        self.embed = TokenEmbedding(n_symbols, n_numerics, d_model)
        make = (lambda: ISAB(d_model, d_model, num_heads, num_inds, ln=ln)) if num_inds else (lambda: SAB(d_model, d_model, num_heads, ln=ln))
        self.enc = nn.ModuleList([make() for _ in range(n_enc)])
        self.pma = PMA(d_model, num_heads, 1, ln=ln)
        self.dec = SAB(d_model, d_model, num_heads, ln=ln)
        self.dropout = nn.Dropout(dropout)
        self.head = nn.Linear(d_model, 2)

    def forward(self, symbols, numerics):
        mask = symbols[:, :, 0] != PAD  # first slot is always the kind symbol
        X = self.embed(symbols, numerics)
        for block in self.enc:
            X = block(X, mask)
        Z = self.dec(self.pma(X, mask))
        return self.head(self.dropout(Z[:, 0]))
