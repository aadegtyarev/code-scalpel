"""Lenient parser for the Mermaid flowchart subset.

Парсер сознательно толерантный: модель может выдавать поломанный
flowchart, и мы должны вернуть хоть что-то, а не валить TUI. Каждая
строка обрабатывается независимо; нераспознанная строка просто
пропускается.

Поддерживаются:
- direction: `flowchart TD/LR/TB`, `graph TD/LR/TB` (TB == TD)
- node shapes: `A`, `A[Label]`, `A(Label)`, `A{Label}`, `A[[Label]]`,
  `A["Label with [brackets]"]`
- edges: `A --> B`, `A -->|label| B`, `A --- B`, `A -.-> B`, `A ==> B`
- комментарии `%%`
- `subgraph X ... end` — пропускаются (узлы внутри парсятся, fence
  игнорируется)

Всё остальное (classDef, click, styling, sequenceDiagram, …) — out of
scope. Если первая значимая строка не из flowchart-семьи, возвращаем
None.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

NodeShape = Literal["rect", "round", "diamond", "subroutine"]
Direction = Literal["TD", "LR"]


@dataclass(frozen=True)
class Node:
    id: str
    label: str
    shape: NodeShape


@dataclass(frozen=True)
class Edge:
    from_id: str
    to_id: str
    label: str | None = None


@dataclass
class Flowchart:
    direction: Direction = "TD"
    nodes: dict[str, Node] = field(default_factory=dict)
    edges: list[Edge] = field(default_factory=list)


# `flowchart TD` / `graph LR` / `flowchart TB` — case-insensitive.
_DIRECTION_RE = re.compile(r"^\s*(?:flowchart|graph)\s+(TD|TB|LR|BT|RL)\b", re.IGNORECASE)

# Все четыре варианта стрелок свелись к одной regex-семье. Порядок
# важен: жирные/пунктирные стрелки должны мэтчиться раньше тонких,
# иначе `=` потеряется. `?P<lab>` ловит `|label|` между стрелкой и
# целью.
_EDGE_RE = re.compile(
    r"""
    ^\s*
    (?P<src>[A-Za-z_][\w-]*)            # source id, бывает с node-spec
    (?P<src_spec>\s*[\[\(\{].*?[\]\)\}])?  # optional inline shape after src
    \s*
    (?P<arrow>==>|-\.->|---|-->)         # arrow (order matters)
    \s*
    (?:\|(?P<lab>[^|]*)\|\s*)?           # optional |edge label|
    (?P<dst>[A-Za-z_][\w-]*)             # dest id
    (?P<dst_spec>\s*[\[\(\{].*?[\]\)\}])? # optional inline shape after dst
    \s*$
    """,
    re.VERBOSE,
)

# Standalone node decl `A[Label]` / `A(Label)` / `A{Label}` / `A[[Label]]`.
# Quoted labels: `A["Label with [brackets]"]` — внутри кавычек скобки
# не считаем разделителями.
_NODE_DECL_RE = re.compile(
    r"""
    ^\s*
    (?P<id>[A-Za-z_][\w-]*)
    (?P<body>\[\[.*?\]\]|\[.*?\]|\(.*?\)|\{.*?\})?
    \s*$
    """,
    re.VERBOSE,
)


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def _parse_node_spec(spec: str | None) -> tuple[NodeShape, str | None]:
    """Convert `[Label]` / `(Label)` / `{Label}` / `[[Label]]` to shape+label.

    Returns (shape, label_or_None). spec=None means bare id.
    """
    if spec is None:
        return "rect", None
    spec = spec.strip()
    if spec.startswith("[[") and spec.endswith("]]"):
        return "subroutine", _strip_quotes(spec[2:-2])
    if spec.startswith("[") and spec.endswith("]"):
        return "rect", _strip_quotes(spec[1:-1])
    if spec.startswith("(") and spec.endswith(")"):
        return "round", _strip_quotes(spec[1:-1])
    if spec.startswith("{") and spec.endswith("}"):
        return "diamond", _strip_quotes(spec[1:-1])
    return "rect", None


def _upsert_node(
    nodes: dict[str, Node],
    node_id: str,
    spec: str | None,
) -> None:
    """Add or upgrade a node entry.

    Если узел уже есть с label=id (declared inline на предыдущем рёбре),
    а сейчас встретилась явная спецификация — апгрейдим. Иначе новый
    узел кладём с дефолтом rect / label=id.
    """
    shape, label = _parse_node_spec(spec)
    if label is None:
        # Bare reference — оставим существующее, или создадим дефолт.
        if node_id not in nodes:
            nodes[node_id] = Node(id=node_id, label=node_id, shape="rect")
        return
    nodes[node_id] = Node(id=node_id, label=label, shape=shape)


def _is_flowchart_header(line: str) -> bool:
    stripped = line.strip()
    if not stripped:
        return False
    head = stripped.split()[0].lower()
    return head in ("flowchart", "graph")


def _is_unsupported_diagram(line: str) -> bool:
    """First non-empty non-comment line decides the type.

    sequenceDiagram / classDiagram больше не "unsupported" на уровне
    пакета — у них собственные парсеры в `sequence.py` / `classes.py`.
    Но для `parse_flowchart` они по-прежнему чужие: возвращаем None,
    чтобы caller (`render_mermaid`) ушёл в нужную ветку dispatch.
    """
    stripped = line.strip().lower()
    # Mermaid diagram types `parse_flowchart` точно не понимает.
    return any(
        stripped.startswith(kw)
        for kw in (
            "sequencediagram",
            "classdiagram",
            "statediagram",
            "erdiagram",
            "gantt",
            "gitgraph",
            "pie",
            "journey",
            "requirementdiagram",
            "mindmap",
            "timeline",
            "quadrantchart",
            "c4context",
            "sankey",
        )
    )


def first_significant_line(source: str) -> str | None:
    """Return the first non-empty, non-`%%` line lowercased + stripped.

    Helper для dispatch в `render_mermaid`: один проход по source,
    каждый под-парсер не должен повторять эту логику.
    """
    if not source:
        return None
    for raw in source.splitlines():
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("%%"):
            continue
        return stripped.lower()
    return None


def parse_flowchart(source: str) -> Flowchart | None:
    """Parse *source* as a Mermaid flowchart.

    Returns None if the source is clearly a different diagram type. An
    empty / commented-out source still returns a Flowchart with no
    nodes — caller can decide what to do with it.
    """
    if not source:
        return Flowchart()

    lines = source.splitlines()
    # Look at the first non-empty, non-comment line to gate diagram type.
    header_seen = False
    direction: Direction = "TD"
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    in_subgraph_depth = 0

    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("%%"):
            continue

        # Bail out early on non-flowchart diagram types.
        if not header_seen and _is_unsupported_diagram(stripped):
            return None

        # Direction header — may appear once at the top.
        m = _DIRECTION_RE.match(line)
        if m:
            header_seen = True
            tok = m.group(1).upper()
            # TB is an alias for TD; BT/RL coerced to TD/LR for simplicity.
            direction = "TD" if tok in ("TD", "TB", "BT") else "LR"
            continue

        # Bare `flowchart` / `graph` (no direction) — accept, keep default.
        if _is_flowchart_header(stripped):
            header_seen = True
            continue

        # Subgraph fence: skip but don't bail. Узлы внутри
        # парсятся обычным образом.
        if stripped.lower().startswith("subgraph"):
            in_subgraph_depth += 1
            header_seen = True
            continue
        if stripped.lower() == "end" and in_subgraph_depth > 0:
            in_subgraph_depth -= 1
            continue

        # Ignored Mermaid features — silent skip.
        low = stripped.lower()
        if low.startswith(("classdef ", "class ", "click ", "style ", "linkstyle ")):
            header_seen = True
            continue

        # Edge?
        m = _EDGE_RE.match(stripped)
        if m:
            header_seen = True
            src = m.group("src")
            dst = m.group("dst")
            _upsert_node(nodes, src, m.group("src_spec"))
            _upsert_node(nodes, dst, m.group("dst_spec"))
            lab = m.group("lab")
            edges.append(
                Edge(
                    from_id=src,
                    to_id=dst,
                    label=lab.strip() if lab else None,
                )
            )
            continue

        # Standalone node declaration?
        m = _NODE_DECL_RE.match(stripped)
        if m:
            header_seen = True
            _upsert_node(nodes, m.group("id"), m.group("body"))
            continue

        # Unrecognized — silently ignore. Modeled output may be noisy.
        continue

    return Flowchart(direction=direction, nodes=nodes, edges=edges)


__all__ = ["Flowchart", "Node", "Edge", "parse_flowchart", "NodeShape", "Direction"]
