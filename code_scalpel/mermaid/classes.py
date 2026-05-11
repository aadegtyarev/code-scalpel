"""Pure-Python ASCII renderer for the Mermaid classDiagram subset.

В отличие от sequenceDiagram, тут структура нодная — классы как
коробки, отношения как стрелки между ними. Поэтому переиспользуем
rank-based layout из flowchart (`layout.layout`): корни в rank=0,
наследники в rank+1. Боксы отличаются от flowchart-боксов трёхсекционным
оформлением (name / fields / methods), а glyph стрелки выбирается под
тип отношения.

Поддерживаем:
- `classDiagram` (заголовок, обязателен)
- `class Name` — пустой класс
- `class Name { +int age; +run(); }` — inline; разделитель `;` или newline
- блочная форма `class Name { ... }` с переносами внутри `{}`
- visibility prefix `+ - # ~`; methods detected by trailing `()`
- relations: `<|--`, `*--`, `o--`, `-->`, `..>`, `--` (+ optional ` : label`)
- annotations `<<interface>>` — парсим, игнорируем

Out of scope: generics `Map~K,V~`, cardinality `"1" --> "*"`, `note for`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

RelationKind = Literal[
    "inheritance",  # <|--
    "composition",  # *--
    "aggregation",  # o--
    "association",  # -->
    "dependency",  # ..>
    "undirected",  # --
]


@dataclass(frozen=True)
class Member:
    """One field or method line of a class box."""

    visibility: str  # "+", "-", "#", "~", or "" if absent
    text: str  # everything after visibility prefix
    is_method: bool


@dataclass
class ClassNode:
    id: str
    fields: list[Member] = field(default_factory=list)
    methods: list[Member] = field(default_factory=list)


@dataclass(frozen=True)
class Relation:
    src: str
    dst: str
    kind: RelationKind
    label: str | None = None


@dataclass
class ClassDiagram:
    nodes: dict[str, ClassNode] = field(default_factory=dict)
    relations: list[Relation] = field(default_factory=list)


# ── parser ────────────────────────────────────────────────────────────────

_CLASS_DECL_RE = re.compile(
    r"""
    ^\s*class\s+
    (?P<name>[A-Za-z_][\w-]*)
    \s*
    (?P<body>\{.*\})?
    \s*$
    """,
    re.VERBOSE | re.DOTALL,
)

# Relation. Порядок альтернатив в regex имеет значение: длинные токены
# должны идти раньше коротких иначе `--` "съест" `<|--`.
_RELATION_RE = re.compile(
    r"""
    ^\s*
    (?P<src>[A-Za-z_][\w-]*)
    \s*
    (?P<rel><\|--|--\|>|\*--|--\*|o--|--o|<\.\.|\.\.>|<--|-->|\.\.|--)
    \s*
    (?P<dst>[A-Za-z_][\w-]*)
    \s*
    (?::\s*(?P<label>.+?))?
    \s*$
    """,
    re.VERBOSE,
)

_ANNOTATION_RE = re.compile(r"<<[^>]+>>")

# Visibility prefix.
_VIS = "+-#~"


def _parse_member(line: str) -> Member | None:
    """Parse a single member line into Member (field or method).

    Skips empty / annotation-only lines.
    """
    line = line.strip().rstrip(";").rstrip(",").strip()
    if not line:
        return None
    if _ANNOTATION_RE.search(line):
        # Annotation-only line: `<<interface>>` — пропускаем.
        if _ANNOTATION_RE.sub("", line).strip() == "":
            return None
        line = _ANNOTATION_RE.sub("", line).strip()
    vis = ""
    if line and line[0] in _VIS:
        vis = line[0]
        line = line[1:].strip()
    is_method = line.endswith(")")
    return Member(visibility=vis, text=line, is_method=is_method)


def _parse_body(node: ClassNode, body: str) -> None:
    """Fill `node.fields`/`node.methods` from a `{ … }` body.

    Принимаем разделители `;` и newline. Аннотации внутри `{ }` тоже
    отлавливаются: `<<interface>>` уходит в /dev/null.
    """
    # Strip the wrapping `{` `}` if present.
    body = body.strip()
    if body.startswith("{"):
        body = body[1:]
    if body.endswith("}"):
        body = body[:-1]
    # Сначала разрываем по newline, потом каждую строку — по `;`.
    chunks: list[str] = []
    for chunk in body.splitlines():
        for sub in chunk.split(";"):
            sub = sub.strip()
            if sub:
                chunks.append(sub)
    for chunk in chunks:
        m = _parse_member(chunk)
        if m is None:
            continue
        if m.is_method:
            node.methods.append(m)
        else:
            node.fields.append(m)


def _ensure_class(diag: ClassDiagram, name: str) -> ClassNode:
    if name not in diag.nodes:
        diag.nodes[name] = ClassNode(id=name)
    return diag.nodes[name]


def _normalize_relation(rel_tok: str) -> tuple[RelationKind, bool]:
    """Map raw relation token to (kind, reversed).

    `reversed=True` when arrow visually points src -> dst но в Mermaid
    syntax token идёт навстречу (например `Duck --|> Animal` где Duck
    наследует Animal). Мы хотим хранить отношения в каноническом
    направлении (parent ← child для inheritance: src = parent).
    """
    # canonical: src=parent, dst=child for inheritance/composition/aggregation
    if rel_tok == "<|--":
        return "inheritance", False  # src is parent
    if rel_tok == "--|>":
        return "inheritance", True  # src is child, flip to parent←child
    if rel_tok == "*--":
        return "composition", False
    if rel_tok == "--*":
        return "composition", True
    if rel_tok == "o--":
        return "aggregation", False
    if rel_tok == "--o":
        return "aggregation", True
    if rel_tok == "-->":
        return "association", False
    if rel_tok == "<--":
        return "association", True
    if rel_tok == "..>":
        return "dependency", False
    if rel_tok == "<..":
        return "dependency", True
    if rel_tok == "..":
        return "dependency", False
    return "undirected", False


def parse_classes(source: str) -> ClassDiagram | None:
    """Parse *source* as a Mermaid classDiagram.

    Returns None if the first significant line isn't `classDiagram`.
    Inline `{ … }` blocks are recognised on a single physical line.
    Multi-line blocks are also handled — we concatenate until the
    matching `}` is found.
    """
    if not source:
        return None
    lines = source.splitlines()
    # Header gate.
    header_seen = False
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        if stripped.lower().startswith("classdiagram"):
            header_seen = True
        break
    if not header_seen:
        return None

    diag = ClassDiagram()

    # Pre-process: join multi-line `{ ... }` bodies into one logical line
    # so the line-based parser can apply uniformly. Состояние: depth
    # отслеживает уровень `{`-вложенности (для нас всегда 0 или 1, но
    # пусть будет общая логика).
    logical_lines: list[str] = []
    buf: list[str] = []
    depth = 0
    for raw in lines:
        if depth > 0:
            buf.append(raw)
            depth += raw.count("{")
            depth -= raw.count("}")
            if depth <= 0:
                logical_lines.append("\n".join(buf))
                buf = []
                depth = 0
            continue
        opens = raw.count("{")
        closes = raw.count("}")
        if opens > closes:
            # Multi-line block opens here.
            depth = opens - closes
            buf = [raw]
            continue
        logical_lines.append(raw)

    if buf:
        # Незакрытый блок — всё равно отдадим как одна строка.
        logical_lines.append("\n".join(buf))

    for raw in logical_lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("%%"):
            continue
        low = stripped.lower()
        if low.startswith("classdiagram"):
            continue
        # `direction LR/TB/…` — silently skip; layout всё равно один.
        if low.startswith("direction"):
            continue
        # `note for X: …` — out of scope, skip.
        if low.startswith("note "):
            continue

        # class decl?
        m = _CLASS_DECL_RE.match(stripped)
        if m:
            name = m.group("name")
            node = _ensure_class(diag, name)
            body = m.group("body")
            if body:
                _parse_body(node, body)
            continue

        # relation?
        m = _RELATION_RE.match(stripped)
        if m:
            kind, reverse = _normalize_relation(m.group("rel"))
            src = m.group("src")
            dst = m.group("dst")
            if reverse:
                src, dst = dst, src
            _ensure_class(diag, src)
            _ensure_class(diag, dst)
            label = m.group("label")
            diag.relations.append(
                Relation(
                    src=src,
                    dst=dst,
                    kind=kind,
                    label=label.strip() if label else None,
                )
            )
            continue

        # `ClassName : +member` — alternative member syntax outside `{}`.
        if ":" in stripped:
            head, _, tail = stripped.partition(":")
            head = head.strip()
            tail = tail.strip()
            if re.match(r"^[A-Za-z_][\w-]*$", head):
                node = _ensure_class(diag, head)
                m2 = _parse_member(tail)
                if m2 is not None:
                    if m2.is_method:
                        node.methods.append(m2)
                    else:
                        node.fields.append(m2)
                continue
        # Unknown — silent skip.

    return diag


# ── rank-based layout (reuses flowchart's engine via duck-typed adapter) ──

# We don't import `layout.layout` directly because it's typed for
# `Flowchart`. Re-implement the small core here: same algorithm
# (longest-path-from-source rank), specialised for class relations
# (inheritance/composition direct downward; association/dependency
# don't drive rank).


@dataclass(frozen=True)
class PlacedClass:
    node: ClassNode
    row: int
    col: int


@dataclass(frozen=True)
class PlacedRelation:
    relation: Relation
    src_row: int
    src_col: int
    dst_row: int
    dst_col: int


def _compute_class_ranks(diag: ClassDiagram) -> dict[str, int]:
    """Rank by longest "hierarchy" path. Composition/aggregation/inheritance
    contribute; association/dependency/undirected don't push children down
    (they're cross-links, not tree edges).
    """
    ids = list(diag.nodes.keys())
    if not ids:
        return {}
    rank: dict[str, int] = {i: 0 for i in ids}
    hier_rel_kinds = {"inheritance", "composition", "aggregation"}
    edges = [r for r in diag.relations if r.kind in hier_rel_kinds]
    max_iters = max(len(ids) * 2, 1)
    for _ in range(max_iters):
        changed = False
        for r in edges:
            if r.src not in rank or r.dst not in rank:
                continue
            cand = rank[r.src] + 1
            if cand > rank[r.dst] and cand < max_iters:
                rank[r.dst] = cand
                changed = True
        if not changed:
            break
    return rank


def _layout_classes(diag: ClassDiagram) -> tuple[list[PlacedClass], list[PlacedRelation]]:
    """Place each class on a (row, col) grid.

    Rows = rank (0 == top). Within a row, classes ordered by first
    appearance in `diag.nodes`. Колонок ровно столько, сколько классов в
    самом широком ранге — позиция остальных в этом ранге дополняется до
    одинаковой ширины.
    """
    ranks = _compute_class_ranks(diag)
    groups: dict[int, list[ClassNode]] = {}
    for nid, node in diag.nodes.items():
        groups.setdefault(ranks.get(nid, 0), []).append(node)
    placed: list[PlacedClass] = []
    pos_by_id: dict[str, tuple[int, int]] = {}
    for r in sorted(groups):
        for c, node in enumerate(groups[r]):
            placed.append(PlacedClass(node=node, row=r, col=c))
            pos_by_id[node.id] = (r, c)
    placed_rel: list[PlacedRelation] = []
    for rel in diag.relations:
        if rel.src not in pos_by_id or rel.dst not in pos_by_id:
            continue
        sr, sc = pos_by_id[rel.src]
        dr, dc = pos_by_id[rel.dst]
        placed_rel.append(
            PlacedRelation(
                relation=rel,
                src_row=sr,
                src_col=sc,
                dst_row=dr,
                dst_col=dc,
            )
        )
    return placed, placed_rel


# ── render ────────────────────────────────────────────────────────────────

GUTTER_V = 2  # blank rows between rank rows
GUTTER_H = 4  # blank cols between siblings within a row
MIN_BOX_W = 10


def _format_member(m: Member) -> str:
    return f"{m.visibility or ' '}{m.text}"


def _box_lines(node: ClassNode, width: int) -> list[str]:
    """Render a class as multi-section box, *width* chars wide.

    Sections:
    - name centered
    - divider
    - fields (skipped entirely if none)
    - divider (only if both fields and methods present)
    - methods (skipped if none)

    Если ни fields ни methods нет — рендерим простой одноразделный box.
    """
    inner_w = max(width - 2, 1)
    name = node.id
    if len(name) > inner_w:
        name = name[: max(inner_w - 1, 1)] + "…"
    pad_total = inner_w - len(name)
    left = pad_total // 2
    right = pad_total - left
    name_line = "|" + " " * left + name + " " * right + "|"
    top = "+" + "-" * inner_w + "+"
    lines = [top, name_line]

    def _render_section(members: list[Member]) -> list[str]:
        out = []
        for m in members:
            txt = _format_member(m)
            if len(txt) > inner_w - 1:
                txt = txt[: max(inner_w - 2, 1)] + "…"
            out.append("|" + " " + txt + " " * (inner_w - 1 - len(txt)) + "|")
        return out

    fields_section = _render_section(node.fields)
    methods_section = _render_section(node.methods)

    if fields_section or methods_section:
        lines.append(top)  # divider after name
        if fields_section:
            lines.extend(fields_section)
            if methods_section:
                lines.append(top)
        if methods_section:
            lines.extend(methods_section)
    lines.append(top)
    return lines


def _compute_widths(placed: list[PlacedClass]) -> dict[int, int]:
    """Per-column width = max(needed) across that column, ≥ MIN_BOX_W.

    "Needed" учитывает: имя класса, длину каждого member-а с visibility
    prefix, capped at 30 чтобы не разносило канвас.
    """
    widths: dict[int, int] = {}
    for pc in placed:
        needed = len(pc.node.id)
        for m in pc.node.fields + pc.node.methods:
            needed = max(needed, len(_format_member(m)))
        needed = min(needed + 4, 32)
        needed = max(needed, MIN_BOX_W)
        col = pc.col
        if widths.get(col, 0) < needed:
            widths[col] = needed
    return widths


def _box_height(node: ClassNode) -> int:
    """Number of rendered lines for a class box.

    Базовый минимум — 3 (top / name / bot). Каждый member добавляет 1.
    Дивайдер между fields и methods — +1, между name и members — +1.
    """
    h = 3  # top, name, bot
    n_fields = len(node.fields)
    n_methods = len(node.methods)
    if n_fields or n_methods:
        h += 1  # divider after name
    h += n_fields
    if n_fields and n_methods:
        h += 1  # divider between fields and methods
    h += n_methods
    return h


def _set(canvas: list[list[str]], row: int, col: int, ch: str) -> None:
    if 0 <= row < len(canvas) and 0 <= col < len(canvas[0]):
        canvas[row][col] = ch


def _draw_box(
    canvas: list[list[str]],
    box: list[str],
    row: int,
    col: int,
) -> None:
    for i, line in enumerate(box):
        for j, ch in enumerate(line):
            if ch == " ":
                continue
            _set(canvas, row + i, col + j, ch)


def _tail_kind(kind: RelationKind) -> str:
    """Char used for the shaft body — `.` for dependency, `|` else.

    Composition vs aggregation: visually идентичны в head glyph, но мы
    различаем через `*` vs `o` маркер рядом с dst-боксом (положим его
    в первую строку ниже head glyph).
    """
    return "." if kind == "dependency" else "|"


def render_classes(diag: ClassDiagram) -> str:
    """Render *diag* to a multi-line ASCII string."""
    if not diag.nodes:
        return ""
    placed, placed_rel = _layout_classes(diag)
    if not placed:
        return ""

    widths = _compute_widths(placed)
    # Per-row height — max box-height of classes in that row.
    rows_by_idx: dict[int, list[PlacedClass]] = {}
    for pc in placed:
        rows_by_idx.setdefault(pc.row, []).append(pc)
    max_row = max(rows_by_idx)
    row_heights = {r: max(_box_height(pc.node) for pc in rows_by_idx[r]) for r in rows_by_idx}

    # Canvas geometry.
    n_cols = max((pc.col for pc in placed), default=-1) + 1
    col_lefts: list[int] = []
    pos = 0
    for c in range(n_cols):
        col_lefts.append(pos)
        pos += widths.get(c, MIN_BOX_W) + GUTTER_H
    total_w = pos - GUTTER_H if n_cols else 0
    row_tops: dict[int, int] = {}
    pos = 0
    for r in range(max_row + 1):
        row_tops[r] = pos
        pos += row_heights.get(r, 3) + GUTTER_V
    total_h = pos - GUTTER_V if row_heights else 0

    canvas: list[list[str]] = [[" "] * max(total_w, 1) for _ in range(max(total_h, 1))]

    # Draw class boxes.
    for pc in placed:
        w = widths.get(pc.col, MIN_BOX_W)
        box = _box_lines(pc.node, w)
        _draw_box(canvas, box, row_tops[pc.row], col_lefts[pc.col])

    # Draw relations.
    for pr in placed_rel:
        _draw_relation(canvas, pr, col_lefts, row_tops, row_heights, widths)

    return "\n".join("".join(r).rstrip() for r in canvas)


def _draw_relation(
    canvas: list[list[str]],
    pr: PlacedRelation,
    col_lefts: list[int],
    row_tops: dict[int, int],
    row_heights: dict[int, int],
    widths: dict[int, int],
) -> None:
    """Draw a relation arrow between two placed classes.

    Strategy:
    - Vertical case (src above dst, same col): draw shaft straight down,
      head glyph just under src box / just above dst box.
    - Same row, different cols: horizontal connector at mid-row.
    - Different row AND col: L-shape — vertical first, then horizontal at
      dst's top.

    Direction convention: src is "parent" for hierarchy edges (rank=0),
    arrow head visually points toward src (child → parent), but for
    association/dependency, head points dst (callee → callee).
    """
    src_w = widths.get(pr.src_col, MIN_BOX_W)
    dst_w = widths.get(pr.dst_col, MIN_BOX_W)
    src_left = col_lefts[pr.src_col]
    dst_left = col_lefts[pr.dst_col]
    src_cx = src_left + src_w // 2
    dst_cx = dst_left + dst_w // 2
    src_top = row_tops[pr.src_row]
    src_bot = src_top + row_heights[pr.src_row] - 1
    dst_top = row_tops[pr.dst_row]
    dst_bot = dst_top + row_heights[pr.dst_row] - 1
    kind = pr.relation.kind
    shaft = _tail_kind(kind)
    label = pr.relation.label

    # Hierarchy edges (inheritance/composition/aggregation): src is the
    # parent (higher in hierarchy), so head sits at src's bottom side and
    # arrow comes up from dst. For directed (association/dependency),
    # head sits at dst's top — pointing toward dst.
    head_at_dst = kind in ("association", "dependency", "undirected")

    if pr.src_row == pr.dst_row and pr.src_col == pr.dst_col:
        return  # self-relation: skip silently

    if pr.src_col == pr.dst_col:
        # Vertical relation.
        if pr.src_row < pr.dst_row:
            top_y, bot_y = src_bot + 1, dst_top - 1
            for y in range(top_y, bot_y + 1):
                _set(canvas, y, src_cx, shaft)
            if head_at_dst:
                _draw_head(canvas, bot_y, src_cx, kind, pointing="down")
            else:
                _draw_head(canvas, top_y, src_cx, kind, pointing="up")
            if label and bot_y > top_y:
                mid_y = (top_y + bot_y) // 2
                _write_label(canvas, mid_y, src_cx + 2, label)
        else:
            top_y, bot_y = dst_bot + 1, src_top - 1
            for y in range(top_y, bot_y + 1):
                _set(canvas, y, src_cx, shaft)
            if head_at_dst:
                _draw_head(canvas, top_y, src_cx, kind, pointing="up")
            else:
                _draw_head(canvas, bot_y, src_cx, kind, pointing="down")
        return

    if pr.src_row == pr.dst_row:
        # Horizontal relation.
        y = src_top + row_heights[pr.src_row] // 2
        if pr.src_col < pr.dst_col:
            x_from = src_left + src_w
            x_to = dst_left - 1
            for x in range(x_from, x_to + 1):
                _set(canvas, y, x, "-" if shaft == "|" else ".")
            if head_at_dst:
                _set(canvas, y, x_to, ">" if kind != "dependency" else ">")
            else:
                _set(canvas, y, x_from, "<")
        else:
            x_from = dst_left + dst_w
            x_to = src_left - 1
            for x in range(x_from, x_to + 1):
                _set(canvas, y, x, "-" if shaft == "|" else ".")
            if head_at_dst:
                _set(canvas, y, x_from, "<" if kind != "dependency" else "<")
            else:
                _set(canvas, y, x_to, ">")
        if label:
            mid_x = (x_from + x_to) // 2
            _write_label(canvas, y - 1, mid_x, label)
        return

    # L-shape: src and dst differ in both axes. Drop a vertical from
    # src_cx down through src's bottom gutter to dst's row, then go
    # horizontal at dst_top - 1 toward dst_cx.
    if pr.src_row < pr.dst_row:
        # Vertical from src_bot+1 down to dst_top-1.
        y_v_end = dst_top - 1
        for y in range(src_bot + 1, y_v_end + 1):
            _set(canvas, y, src_cx, shaft)
        # Horizontal on row y_v_end between src_cx and dst_cx.
        if dst_cx > src_cx:
            for x in range(src_cx + 1, dst_cx + 1):
                _set(canvas, y_v_end, x, "-" if shaft == "|" else ".")
        else:
            for x in range(dst_cx, src_cx):
                _set(canvas, y_v_end, x, "-" if shaft == "|" else ".")
        _set(canvas, y_v_end, src_cx, "+")
        if head_at_dst:
            _draw_head(canvas, y_v_end, dst_cx, kind, pointing="down")
        else:
            _draw_head(canvas, src_bot + 1, src_cx, kind, pointing="up")
    else:
        y_v_end = dst_bot + 1
        for y in range(y_v_end, src_top):
            _set(canvas, y, src_cx, shaft)
        if dst_cx > src_cx:
            for x in range(src_cx + 1, dst_cx + 1):
                _set(canvas, y_v_end, x, "-" if shaft == "|" else ".")
        else:
            for x in range(dst_cx, src_cx):
                _set(canvas, y_v_end, x, "-" if shaft == "|" else ".")
        _set(canvas, y_v_end, src_cx, "+")
        if head_at_dst:
            _draw_head(canvas, y_v_end, dst_cx, kind, pointing="up")
        else:
            _draw_head(canvas, src_top - 1, src_cx, kind, pointing="down")


def _draw_head(
    canvas: list[list[str]],
    y: int,
    x: int,
    kind: RelationKind,
    pointing: str,
) -> None:
    """Paint a 1- or 2-char head glyph identifying *kind* at (y, x).

    pointing ∈ {"up", "down"} — направление, в которое смотрит стрелка.
    `pointing="up"` означает head на верхней стороне shaft'а (например
    дочерний класс → родительский в наследовании).
    """
    if kind == "inheritance":
        # Triangle proxy. Up-facing: `/\` на одной строке.
        if pointing == "up":
            _set(canvas, y, x - 1, "/")
            _set(canvas, y, x, "\\")
        else:
            _set(canvas, y, x - 1, "\\")
            _set(canvas, y, x, "/")
        return
    if kind == "composition":
        # Filled diamond — `<>` с `*` маркером рядом для контраста.
        _set(canvas, y, x - 1, "<")
        _set(canvas, y, x, ">")
        _set(canvas, y, x + 1, "*")
        return
    if kind == "aggregation":
        # Hollow diamond — `<>` + `o` marker (opp of composition).
        _set(canvas, y, x - 1, "<")
        _set(canvas, y, x, ">")
        _set(canvas, y, x + 1, "o")
        return
    if kind in ("association", "dependency"):
        _set(canvas, y, x, "v" if pointing == "down" else "^")
        return
    # undirected — no head.


def _write_label(
    canvas: list[list[str]],
    y: int,
    x: int,
    label: str,
) -> None:
    if y < 0 or y >= len(canvas):
        return
    for i, ch in enumerate(label):
        _set(canvas, y, x + i, ch)


__all__ = [
    "ClassDiagram",
    "ClassNode",
    "Relation",
    "Member",
    "parse_classes",
    "render_classes",
]
