"""Abstract full-run simulator for Silent A10.

The simulator never launches the game. Out-of-combat rules (map, encounter
pools, rewards, shops, rest sites, events, ancients) are fitted from public
Spire Codex ``.run`` histories (``sim.tables``); combat outcomes come from a
pluggable oracle (``sim.oracle``), by default the trained expected-HP-loss
model ``F`` from ``train.predict``.

``sim.calibrate`` compares simulator rollouts against held-out human runs and
writes a deviation report.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
