"""ASCII renderer for the laid-out flowchart grid.

Каждая ячейка грида превращается в "коробку" (3 строки высотой
для rect/round, 1 строка для diamond's compact form). Между ячейками
оставляем vertical/horizontal gutter, через который проводим стрелки.

Стрелки рисуются как `|` + `v` (вертикальные) или `-` + `>`
(горизонтальные). Перекрытия не решаем — последняя нарисованная
стрелка побеждает; это компромисс ради простоты, но flowchart с
большим crossings и так читается плохо в ASCII.
"""

from __future__ import annotations

from code_scalpel.mermaid.layout import Grid, PlacedEdge, PlacedNode

# ── box geometry ──────────────────────────────────────────────────────────
# Каждая ячейка занимает CELL_W колонок и CELL_H строк в финальном
# canvas. Достаточно widely чтобы вместить узел с label до ~14 символов
# плюс border. Между ячейками оставляем GUTTER_H/W пустых строк/колонок
# для стрелок.
CELL_H = 3
GUTTER_V = 2  # vertical space (rows) between ranks in TD
GUTTER_H = 4  # horizontal space (cols) between cells

# Минимальная ширина коробки. Расширяется под длинный label.
MIN_BOX_W = 5


def _box_lines(node: PlacedNode, width: int) -> list[str]:
    """Render a single node as a list of 3 strings of equal *width*."""
    label = node.node.label
    # Усекаем label до доступного места внутри border (-2 на края).
    inner_w = max(width - 2, 1)
    if len(label) > inner_w:
        label = label[: max(inner_w - 1, 1)] + "…"
    pad_total = inner_w - len(label)
    left = pad_total // 2
    right = pad_total - left
    body = " " * left + label + " " * right

    shape = node.node.shape
    if shape == "diamond":
        # Compact diamond: < label > обрамлён горизонтальными '-' для
        # узнаваемости. 3 строки чтобы совпасть по высоте с rect и не
        # ломать gutter / arrowhead positioning.
        top = " " + "-" * inner_w + " "
        mid = "<" + body + ">"
        bot = " " + "-" * inner_w + " "
        return [top, mid, bot]
    if shape == "round":
        top = "." + "-" * inner_w + "."
        mid = "(" + body + ")"
        bot = "'" + "-" * inner_w + "'"
        return [top, mid, bot]
    # rect / subroutine — same box.
    top = "+" + "-" * inner_w + "+"
    mid = "|" + body + "|"
    bot = "+" + "-" * inner_w + "+"
    return [top, mid, bot]


def _compute_box_widths(grid: Grid) -> list[int]:
    """One width per column: max(label_len)+2 over the column, ≥ MIN_BOX_W."""
    if not grid:
        return []
    n_cols = max((len(row) for row in grid), default=0)
    widths = [MIN_BOX_W] * n_cols
    for row in grid:
        for col, cell in enumerate(row):
            if cell is None:
                continue
            # +2 — на border. Кэп сверху, чтобы один длинный label не
            # разносил весь канвас (диаграмма должна влезть в TUI).
            wanted = min(len(cell.node.label) + 2, 24)
            if wanted > widths[col]:
                widths[col] = wanted
    return widths


def _column_starts(widths: list[int]) -> list[int]:
    """Left-edge column index of each grid column on the canvas."""
    starts = []
    pos = 0
    for w in widths:
        starts.append(pos)
        pos += w + GUTTER_H
    return starts


def _row_starts(grid: Grid) -> list[int]:
    """Top-edge row index of each grid row on the canvas."""
    starts = []
    pos = 0
    for _ in grid:
        starts.append(pos)
        pos += CELL_H + GUTTER_V
    return starts


def _draw_box(
    canvas: list[list[str]],
    box: list[str],
    row: int,
    col: int,
) -> None:
    """Paint *box* (list of equal-length lines) at canvas[row+i][col+j]."""
    for i, line in enumerate(box):
        for j, ch in enumerate(line):
            if ch == " ":
                continue
            canvas[row + i][col + j] = ch


def _set(canvas: list[list[str]], row: int, col: int, ch: str) -> None:
    """Set a single canvas cell, bounds-safe."""
    if 0 <= row < len(canvas) and 0 <= col < len(canvas[0]):
        canvas[row][col] = ch


def _draw_edge(
    canvas: list[list[str]],
    edge: PlacedEdge,
    col_starts: list[int],
    row_starts: list[int],
    widths: list[int],
    direction: str,
) -> None:
    """Draw an ASCII arrow from edge.src_* to edge.dst_*.

    Реализация: рисуем "L-образный" путь — сначала по основной оси
    (вертикальной для TD, горизонтальной для LR), потом по второй.
    Стрелка-наконечник ставится в последнюю клетку перед dst-боксом.
    Label рёбра (если есть) вписывается в середину "длинной" части.
    """
    sr, sc = edge.src_row, edge.src_col
    dr, dc = edge.dst_row, edge.dst_col

    # Bottom-center of src box / top-center of dst box for TD.
    src_w = widths[sc]
    dst_w = widths[dc]
    src_top = row_starts[sr]
    src_bot = src_top + CELL_H - 1
    src_left = col_starts[sc]
    src_cx = src_left + src_w // 2
    dst_top = row_starts[dr]
    dst_left = col_starts[dc]
    dst_cx = dst_left + dst_w // 2
    src_right = src_left + src_w - 1
    src_my = src_top + CELL_H // 2
    dst_my = dst_top + CELL_H // 2
    dst_right = dst_left + dst_w - 1

    label = edge.edge.label

    if direction == "TD":
        # Forward edge: src is above dst (sr < dr). Draw a vertical line
        # from src_cx, src_bot+1 down through the gutter, then turn
        # horizontally if columns differ.
        if sr == dr and sc != dc:
            # Same-rank edge (rare; usually back-edge / sibling). Draw
            # a horizontal segment at the middle row of the boxes.
            y = src_my
            if sc < dc:
                for x in range(src_right + 1, dst_left):
                    _set(canvas, y, x, "-")
                _set(canvas, y, dst_left - 1, ">")
            else:
                for x in range(dst_right + 1, src_left):
                    _set(canvas, y, x, "-")
                _set(canvas, y, dst_right + 1, "<")
            if label:
                _draw_label_horizontal(canvas, y - 1, src_right, dst_left, label)
            return

        # Vertical segment.
        y_from = src_bot + 1 if sr <= dr else src_top - 1
        y_to = dst_top - 1 if sr <= dr else dst_top + CELL_H
        step = 1 if y_to >= y_from else -1
        for y in range(y_from, y_to + step, step):
            _set(canvas, y, src_cx, "|")
        # Horizontal segment if columns differ — draw at y_to row.
        if sc != dc:
            y_h = y_to
            if dst_cx > src_cx:
                for x in range(src_cx + 1, dst_cx + 1):
                    _set(canvas, y_h, x, "-")
            else:
                for x in range(dst_cx, src_cx):
                    _set(canvas, y_h, x, "-")
            # Re-establish the "corner" at the bend.
            _set(canvas, y_h, src_cx, "+")
        # Arrowhead — на ячейке прямо над dst-боксом.
        if sr <= dr:
            _set(canvas, dst_top - 1, dst_cx, "v")
        else:
            _set(canvas, dst_top + CELL_H, dst_cx, "^")
        # Label — между bend и dst для bend-edge'й, сбоку от вертикали
        # для прямых. Разные dst-колонки → разные средние точки → нет
        # перекрытия даже когда из одной развилки выходит несколько меток.
        if label:
            if sc != dc:
                # Над dst-боксом, чтобы для каждой ветки своя метка.
                _draw_label_horizontal_at(canvas, y_to - 1, dst_cx, label)
            else:
                mid_y = (y_from + y_to) // 2
                _draw_label_vertical(canvas, mid_y, src_cx + 2, label)
    else:
        # LR: src is left of dst. Horizontal segment first, then
        # vertical if rows differ.
        if sc == dc and sr != dr:
            x = src_cx
            if sr < dr:
                for y in range(src_bot + 1, dst_top):
                    _set(canvas, y, x, "|")
                _set(canvas, dst_top - 1, x, "v")
            else:
                for y in range(dst_top + CELL_H, src_top):
                    _set(canvas, y, x, "|")
                _set(canvas, dst_top + CELL_H, x, "^")
            if label:
                _draw_label_vertical(canvas, (src_bot + dst_top) // 2, x + 2, label)
            return

        x_from = src_right + 1 if sc <= dc else src_left - 1
        x_to = dst_left - 1 if sc <= dc else dst_right + 1
        step = 1 if x_to >= x_from else -1
        for x in range(x_from, x_to + step, step):
            _set(canvas, src_my, x, "-")
        if sr != dr:
            x_v = x_to
            if dst_my > src_my:
                for y in range(src_my + 1, dst_my + 1):
                    _set(canvas, y, x_v, "|")
            else:
                for y in range(dst_my, src_my):
                    _set(canvas, y, x_v, "|")
            _set(canvas, src_my, x_v, "+")
            _set(canvas, dst_my, x_v, "+")
        # Arrowhead.
        if sc <= dc:
            _set(canvas, dst_my, dst_left - 1, ">")
        else:
            _set(canvas, dst_my, dst_right + 1, "<")
        if label:
            mid_x = (x_from + x_to) // 2
            _draw_label_horizontal_at(canvas, src_my - 1, mid_x, label)


def _draw_label_horizontal(
    canvas: list[list[str]],
    row: int,
    x_left: int,
    x_right: int,
    label: str,
) -> None:
    """Write *label* roughly centered between x_left and x_right at *row*."""
    span = x_right - x_left
    if span <= 1:
        return
    mid = (x_left + x_right) // 2
    start = mid - len(label) // 2
    _draw_label_horizontal_at(canvas, row, start + len(label) // 2, label)


def _draw_label_horizontal_at(
    canvas: list[list[str]],
    row: int,
    center_x: int,
    label: str,
) -> None:
    start = center_x - len(label) // 2
    if row < 0 or row >= len(canvas):
        return
    for i, ch in enumerate(label):
        _set(canvas, row, start + i, ch)


def _draw_label_vertical(
    canvas: list[list[str]],
    row: int,
    col: int,
    label: str,
) -> None:
    """Write *label* horizontally starting at (row, col) — used as a side note."""
    if row < 0 or row >= len(canvas):
        return
    for i, ch in enumerate(label):
        _set(canvas, row, col + i, ch)


def _detect_direction(grid: Grid) -> str:
    """Heuristic: rows >= cols means TD layout; otherwise LR.

    Не идеально, но рендерер уже работает с placement-координатами, а
    направление нужно только чтобы выбрать стиль рисования стрелок.
    Алтернатива — пробрасывать direction через grid; для простоты
    оставим heuristic, TD как дефолт.
    """
    if not grid:
        return "TD"
    rows = len(grid)
    cols = len(grid[0]) if grid else 0
    if cols > rows:
        return "LR"
    return "TD"


def render(grid: Grid, edges: list[PlacedEdge], direction: str | None = None) -> str:
    """Render *grid* + *edges* to a multi-line ASCII string.

    Empty grid returns the empty string — caller can render a hint like
    "(empty flowchart)" if it wants something visible.
    """
    if not grid or all(cell is None for row in grid for cell in row):
        return ""

    widths = _compute_box_widths(grid)
    col_starts = _column_starts(widths)
    row_starts = _row_starts(grid)

    total_w = sum(widths) + GUTTER_H * max(len(widths) - 1, 0) + 1
    total_h = len(grid) * CELL_H + GUTTER_V * max(len(grid) - 1, 0)
    # Резерв справа: длиннейшая метка вертикального edge'а должна
    # помещаться сбоку от линии. Без этого `A -->|long| B` в TD-режиме
    # обрезается до 1-2 символов.
    max_label_len = max(
        (len(e.edge.label) for e in edges if e.edge.label and e.src_col == e.dst_col),
        default=0,
    )
    if max_label_len:
        total_w += max_label_len + 2

    canvas: list[list[str]] = [[" "] * total_w for _ in range(total_h)]

    # Boxes first; arrows drawn on top so arrowheads survive on the
    # canvas edge of the destination box.
    for row in grid:
        for cell in row:
            if cell is None:
                continue
            box = _box_lines(cell, widths[cell.col])
            _draw_box(canvas, box, row_starts[cell.row], col_starts[cell.col])

    dir_ = direction or _detect_direction(grid)
    # Сначала рисуем рёбра с bend (sr/sc != dr/dc по обоим осям), чтобы
    # позже прямые edge'и не получили затёртый bend-плюс на месте своих
    # arrow-heads.
    bend_edges = [e for e in edges if e.src_row != e.dst_row and e.src_col != e.dst_col]
    straight_edges = [e for e in edges if e not in bend_edges]
    for edge in bend_edges + straight_edges:
        _draw_edge(canvas, edge, col_starts, row_starts, widths, dir_)

    # Collapse to string, trim trailing whitespace per line.
    return "\n".join("".join(row).rstrip() for row in canvas)


__all__ = ["render"]
