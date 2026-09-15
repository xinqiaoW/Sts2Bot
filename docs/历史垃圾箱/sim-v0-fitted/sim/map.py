"""Act map generation.

The ``.run`` histories only record the path a player took, not the whole map,
so the layout algorithm cannot be fitted; it follows the well-known Slay the
Spire scheme (``width`` columns, ``paths`` random upward walks, boss on top)
with the row structure verified in the histories:

* floor 0 is the act's ancient (not part of the grid),
* row 1 is always a monster,
* the treasure row and the final rest-site row are fixed per act,
* elites and rest sites only appear from ``first_elite_row``,
* no rest site in the two rows before the final rest row,
* a child never repeats its parent's type for elite/rest/shop.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np


@dataclass
class MapNode:
    id: int
    row: int          # 1..rows
    col: int
    type: str         # monster/elite/rest_site/shop/unknown/treasure/boss
    children: list[int] = field(default_factory=list)
    parents: list[int] = field(default_factory=list)


@dataclass
class ActMap:
    rows: int
    nodes: dict[int, MapNode]
    starts: list[int]
    boss: int

    def row_nodes(self, row):
        return [n for n in self.nodes.values() if n.row == row]

    def to_dict(self):
        return {'rows': self.rows, 'boss': self.boss, 'starts': list(self.starts),
                'nodes': {str(i): {'row': n.row, 'col': n.col, 'type': n.type, 'children': list(n.children)}
                          for i, n in self.nodes.items()}}


def _weighted_choice(rng: np.random.Generator, weights: dict[str, float], exclude=()):
    items = [(k, w) for k, w in weights.items() if k not in exclude and w > 0]
    if not items:
        items = [(k, w) for k, w in weights.items() if w > 0]
    keys, ws = zip(*items)
    ws = np.asarray(ws, dtype=float)
    return keys[rng.choice(len(keys), p=ws / ws.sum())]


def generate_map(rng: np.random.Generator, act_spec: dict, structure: dict, row_weights: dict | None = None) -> ActMap:
    """``row_weights`` (optional) maps row -> {type: weight} and overrides the static
    generator weights for rows that are not fixed by structure. The simulator passes
    the per-floor mix of node types humans *visited* (``tables['row_types']``), which is
    the only observable proxy for the generated mix."""
    rows = act_spec['rows']
    gen = structure['map_generator']
    width, n_paths = gen['width'], gen['paths']
    first_elite = structure['first_elite_row']
    treasure_row = act_spec['treasure_row']
    # Random upward walks; nodes are (row, col) cells, edges follow the walks.
    cells: dict[tuple[int, int], set[tuple[int, int]]] = {}
    start_cols = []
    for p in range(n_paths):
        col = int(rng.integers(width))
        if p == 1:
            while col == start_cols[0]:
                col = int(rng.integers(width))
        start_cols.append(col)
        prev = (1, col)
        cells.setdefault(prev, set())
        for row in range(2, rows + 1):
            step = int(rng.integers(-1, 2))
            col = min(width - 1, max(0, col + step))
            cur = (row, col)
            cells.setdefault(cur, set())
            cells[prev].add(cur)
            prev = cur
    ids = {cell: i for i, cell in enumerate(sorted(cells))}
    nodes = {ids[c]: MapNode(ids[c], c[0], c[1], '') for c in cells}
    for cell, children in cells.items():
        for child in children:
            nodes[ids[cell]].children.append(ids[child])
            nodes[ids[child]].parents.append(ids[cell])
    boss_id = len(nodes)
    nodes[boss_id] = MapNode(boss_id, rows + 1, width // 2, 'boss')
    for n in list(nodes.values()):
        if n.row == rows:
            n.children.append(boss_id)
            nodes[boss_id].parents.append(n.id)
    # Type assignment, row by row so parent types are known.
    for row in range(1, rows + 1):
        for n in sorted((n for n in nodes.values() if n.row == row), key=lambda n: n.col):
            if row == 1:
                n.type = 'monster'
            elif row == treasure_row:
                n.type = 'treasure'
            elif row == rows:
                n.type = 'rest_site'
            else:
                if row_weights and row_weights.get(row):
                    weights = {t: w for t, w in row_weights[row].items() if t in ('monster', 'elite', 'rest_site', 'shop', 'unknown')}
                else:
                    weights = dict(gen['early_rows'] if row < first_elite else gen['late_rows'])
                if row < first_elite:
                    weights.pop('elite', None); weights.pop('rest_site', None)
                if row >= rows - 2:
                    weights.pop('rest_site', None)
                exclude = {nodes[p].type for p in n.parents} & {'elite', 'rest_site', 'shop'}
                n.type = _weighted_choice(rng, weights, exclude)
    starts = sorted({ids[(1, c)] for c in start_cols})
    return ActMap(rows, nodes, starts, boss_id)
