"""Training, evaluation and inference for the expected-HP-loss model.

Reads frozen snapshots exported from the 8 s collection databases (real v3/v4 and
mutation v1/v2), never the live databases, and never writes back to them.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
