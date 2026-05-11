"""Tests for the rank-based flowchart layout.

Главное — два инварианта:
1. Линейная цепочка укладывается в одну колонку (TD) / строку (LR).
2. Циклы не зацикливают алгоритм и не вызывают exception.
"""

from __future__ import annotations

from code_scalpel.mermaid.layout import layout
from code_scalpel.mermaid.parser import parse_flowchart


def _placed_cells(grid):  # type: ignore[no-untyped-def]
    """Helper: yield (row, col, node_id) for non-empty cells."""
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if cell is not None:
                yield r, c, cell.node.id


def test_linear_td_three_nodes_three_rows() -> None:
    fc = parse_flowchart("flowchart TD\nA --> B\nB --> C")
    assert fc is not None
    grid, _edges = layout(fc)
    assert len(grid) == 3
    assert all(len(row) == 1 for row in grid)
    cells = list(_placed_cells(grid))
    assert cells == [(0, 0, "A"), (1, 0, "B"), (2, 0, "C")]


def test_linear_lr_three_nodes_three_cols() -> None:
    fc = parse_flowchart("flowchart LR\nA --> B\nB --> C")
    assert fc is not None
    grid, _edges = layout(fc)
    assert len(grid) == 1
    assert len(grid[0]) == 3
    cells = list(_placed_cells(grid))
    assert {c[2] for c in cells} == {"A", "B", "C"}


def test_branching_one_row_two_columns_at_rank1() -> None:
    """A->B, A->C: A at rank 0, B+C at rank 1 → row 0 has 1 cell, row 1 has 2."""
    fc = parse_flowchart("flowchart TD\nA --> B\nA --> C")
    assert fc is not None
    grid, _edges = layout(fc)
    # 2 rows
    assert len(grid) == 2
    # First row has A (col 0), second row has B and C.
    placed = list(_placed_cells(grid))
    assert (0, 0, "A") in placed
    rank1 = {(r, c, nid) for (r, c, nid) in placed if r == 1}
    assert {nid for _, _, nid in rank1} == {"B", "C"}


def test_cycle_does_not_infinite_loop() -> None:
    """A -> B -> A: layout must finish in finite time and produce a grid."""
    fc = parse_flowchart("flowchart TD\nA --> B\nB --> A")
    assert fc is not None
    grid, edges = layout(fc)
    # 2 nodes, both placed; rank bounded so grid is finite.
    placed_ids = {nid for _, _, nid in _placed_cells(grid)}
    assert placed_ids == {"A", "B"}
    assert len(edges) == 2


def test_self_loop_tolerated() -> None:
    """A -> A: single node, single back-edge. No infinite loop."""
    fc = parse_flowchart("flowchart TD\nA --> A")
    assert fc is not None
    grid, edges = layout(fc)
    placed_ids = {nid for _, _, nid in _placed_cells(grid)}
    assert placed_ids == {"A"}
    assert len(edges) == 1


def test_empty_flowchart_returns_empty_grid() -> None:
    fc = parse_flowchart("flowchart TD")
    assert fc is not None
    grid, edges = layout(fc)
    assert grid == []
    assert edges == []


def test_edges_carry_coordinates() -> None:
    fc = parse_flowchart("flowchart TD\nA --> B")
    assert fc is not None
    _grid, edges = layout(fc)
    assert len(edges) == 1
    assert edges[0].src_row == 0
    assert edges[0].dst_row == 1


def test_diamond_branching_layout() -> None:
    """Decision diamond with two branches converging."""
    src = "flowchart TD\nA{D} --> B\nA --> C\nB --> E\nC --> E\n"
    fc = parse_flowchart(src)
    assert fc is not None
    grid, edges = layout(fc)
    # 3 ranks: A (0), {B,C} (1), E (2)
    assert len(grid) == 3
    placed_ids = {nid for _, _, nid in _placed_cells(grid)}
    assert placed_ids == {"A", "B", "C", "E"}
    assert len(edges) == 4
