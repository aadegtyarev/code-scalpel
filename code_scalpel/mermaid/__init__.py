"""Pure-Python ASCII renderer for the Mermaid flowchart subset.

Используется как первый ярус fallback-каскада в MermaidCard: модель
выдаёт ```mermaid``` блок, мы пытаемся отрисовать его прямо в TUI без
обращения к Node-CLI или сети. Поддерживается только flowchart-семья
(`flowchart TD/LR`, `graph TD/LR`); для остальных типов диаграмм
возвращаем None и caller падает в текстовый fallback.
"""

from __future__ import annotations

from code_scalpel.mermaid.layout import layout
from code_scalpel.mermaid.parser import parse_flowchart
from code_scalpel.mermaid.render import render


def render_mermaid(source: str) -> str | None:
    """Render a Mermaid *source* string to ASCII art.

    Returns the rendered string, or None if the diagram type isn't a
    flowchart (sequenceDiagram, classDiagram, gantt, gitgraph, ...).
    Never raises: malformed flowchart lines are silently skipped so the
    weak local model's output can't crash the TUI.
    """
    flowchart = parse_flowchart(source)
    if flowchart is None:
        return None
    grid, edges = layout(flowchart)
    return render(grid, edges, direction=flowchart.direction)


__all__ = ["render_mermaid", "parse_flowchart", "layout", "render"]
