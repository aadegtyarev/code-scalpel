"""Pure-Python ASCII renderer for a useful Mermaid subset.

Используется как первый ярус fallback-каскада в MermaidCard: модель
выдаёт ```mermaid``` блок, мы пытаемся отрисовать его прямо в TUI без
обращения к Node-CLI или сети.

Supported diagram types:
- `flowchart` / `graph` (TD, LR, TB) — `parser.py` + `layout.py` +
  `render.py`
- `sequenceDiagram` — `sequence.py` (actors-as-columns layout, different
  shape from rank-based flowchart)
- `classDiagram` — `classes.py` (rank-based, reuses the flowchart layout
  idea with multi-section boxes and per-relation head glyphs)

Anything else (gantt, gitgraph, statediagram, …) returns None and the
caller falls back to a raw-source view.
"""

from __future__ import annotations

from code_scalpel.mermaid.classes import parse_classes, render_classes
from code_scalpel.mermaid.layout import layout
from code_scalpel.mermaid.parser import first_significant_line, parse_flowchart
from code_scalpel.mermaid.render import render
from code_scalpel.mermaid.sequence import parse_sequence
from code_scalpel.mermaid.sequence import render as render_sequence


def render_mermaid(source: str) -> str | None:
    """Render a Mermaid *source* string to ASCII art.

    Dispatch на тип диаграммы по первой значимой строке:
    - `flowchart TD/LR/graph …` → flowchart pipeline
    - `sequenceDiagram` → sequence pipeline
    - `classDiagram` → classes pipeline
    - всё остальное → None (caller падает в текстовый fallback)

    Never raises: malformed lines внутри поддерживаемого типа silently
    пропускаются, чтобы слабая локальная модель не могла уронить TUI.
    """
    first = first_significant_line(source)
    if first is None:
        # Пустой / только комментарии — обращаемся с flowchart как с
        # дефолтом (исторически возвращали Flowchart() для совместимости).
        flow = parse_flowchart(source)
        if flow is None:
            return None
        grid, edges = layout(flow)
        return render(grid, edges, direction=flow.direction)

    if first.startswith("sequencediagram"):
        seq = parse_sequence(source)
        if seq is None:
            return None
        return render_sequence(seq)

    if first.startswith("classdiagram"):
        diag = parse_classes(source)
        if diag is None:
            return None
        return render_classes(diag)

    # Default branch — flowchart (включая bare `A --> B` без явного
    # `flowchart TD` header).
    flow = parse_flowchart(source)
    if flow is None:
        return None
    grid, edges = layout(flow)
    return render(grid, edges, direction=flow.direction)


__all__ = [
    "render_mermaid",
    "parse_flowchart",
    "parse_sequence",
    "parse_classes",
    "layout",
    "render",
]
