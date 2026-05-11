"""Rank-based layout for parsed Mermaid flowcharts.

Идея простая: каждому узлу присваиваем rank = длина самого длинного
пути от любого source (узла с in-degree 0). BFS / iterative
relaxation, cycles защищены visited-set + maximum-depth-cap. Узлы с
одинаковым rank складываем в одну "линию" (строку для TD,
столбец для LR), детерминированный порядок — по порядку появления
узла в исходнике.
"""

from __future__ import annotations

from dataclasses import dataclass

from code_scalpel.mermaid.parser import Edge, Flowchart, Node


@dataclass(frozen=True)
class PlacedNode:
    """A node with its grid coordinates (row, col)."""

    node: Node
    row: int
    col: int


@dataclass(frozen=True)
class PlacedEdge:
    """An edge with computed source/target grid coordinates."""

    edge: Edge
    src_row: int
    src_col: int
    dst_row: int
    dst_col: int


# Grid is a 2D list of cells, where None means an empty position.
Grid = list[list[PlacedNode | None]]


def _compute_ranks(flowchart: Flowchart) -> dict[str, int]:
    """Longest-path rank from any source, cycle-safe.

    Алгоритм: повторяем релаксацию edges, пока что-то меняется или
    пока не упёрлись в cap = N*2 итераций. Cap гарантирует завершение
    в любом графе, включая циклы — back-edge просто не повысит rank
    выше, чем уже видели.
    """
    node_ids = list(flowchart.nodes.keys())
    if not node_ids:
        return {}

    rank: dict[str, int] = {nid: 0 for nid in node_ids}
    # Cap — защита от любых патологий. Достаточно O(V) проходов чтобы
    # rank стабилизировался в ациклическом графе; на циклах cap режет.
    max_iters = max(len(node_ids) * 2, 1)
    for _ in range(max_iters):
        changed = False
        for edge in flowchart.edges:
            if edge.from_id not in rank or edge.to_id not in rank:
                continue
            candidate = rank[edge.from_id] + 1
            # На циклах rank растёт максимум до cap, дальше break.
            if candidate > rank[edge.to_id] and candidate < max_iters:
                rank[edge.to_id] = candidate
                changed = True
        if not changed:
            break
    return rank


def _group_by_rank(
    flowchart: Flowchart,
    ranks: dict[str, int],
) -> dict[int, list[Node]]:
    """Group nodes by rank, preserving insertion order within each rank."""
    groups: dict[int, list[Node]] = {}
    for nid, node in flowchart.nodes.items():
        r = ranks.get(nid, 0)
        groups.setdefault(r, []).append(node)
    return groups


def layout(flowchart: Flowchart) -> tuple[Grid, list[PlacedEdge]]:
    """Place every node on a 2D grid; return (grid, placed_edges).

    For direction="TD": rank == row, sibling index == col.
    For direction="LR": rank == col, sibling index == row.

    Empty flowchart → 0×0 grid + empty edge list.
    """
    if not flowchart.nodes:
        return [], []

    ranks = _compute_ranks(flowchart)
    groups = _group_by_rank(flowchart, ranks)

    max_rank = max(groups) if groups else 0
    max_width = max((len(group) for group in groups.values()), default=0)

    # placement[node_id] -> (row, col)
    placement: dict[str, tuple[int, int]] = {}
    grid: Grid

    if flowchart.direction == "TD":
        rows = max_rank + 1
        cols = max_width
        grid = [[None] * cols for _ in range(rows)]
        for r in range(rows):
            for col_idx, node in enumerate(groups.get(r, [])):
                placement[node.id] = (r, col_idx)
                grid[r][col_idx] = PlacedNode(node=node, row=r, col=col_idx)
    else:
        # LR — transpose: rank -> col, sibling -> row.
        rows = max_width
        cols = max_rank + 1
        grid = [[None] * cols for _ in range(rows)]
        for c in range(cols):
            for row_idx, node in enumerate(groups.get(c, [])):
                placement[node.id] = (row_idx, c)
                grid[row_idx][c] = PlacedNode(node=node, row=row_idx, col=c)

    placed_edges: list[PlacedEdge] = []
    for edge in flowchart.edges:
        if edge.from_id not in placement or edge.to_id not in placement:
            continue
        src_row, src_col = placement[edge.from_id]
        dst_row, dst_col = placement[edge.to_id]
        placed_edges.append(
            PlacedEdge(
                edge=edge,
                src_row=src_row,
                src_col=src_col,
                dst_row=dst_row,
                dst_col=dst_col,
            )
        )

    return grid, placed_edges


__all__ = ["layout", "PlacedNode", "PlacedEdge", "Grid"]
