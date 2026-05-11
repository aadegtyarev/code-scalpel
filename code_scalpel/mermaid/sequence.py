"""Pure-Python ASCII renderer for the Mermaid sequenceDiagram subset.

Структура диаграммы фундаментально другая по сравнению с flowchart:
участники (actors) идут слева направо как колонки, сообщения — сверху
вниз как строки. Каждый actor имеет вертикальную "lifeline" — пунктир
до самого низа.

Поддерживаем:
- `sequenceDiagram` (заголовок, обязателен)
- `participant Alice` / `participant Alice as A` (alias)
- `actor Bob` — синонимично participant
- сообщения: `->>`, `-->>`, `->`, `-)`
- `Note over A,B: text`, `Note left of A: text`, `Note right of A: text`
- `activate X` / `deactivate X` — парсим, но не визуализируем
- блоки `loop … end`, `alt … end`, `par … end`, `opt … end`,
  `else`, `and` — парсятся как fence, внутренние сообщения рендерятся
  плоским потоком (без вложенных коробок)
- `%%` комментарии
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

ArrowKind = Literal["solid", "dashed", "open", "plain"]
NoteSide = Literal["over", "left", "right"]


@dataclass(frozen=True)
class Participant:
    """Single column in the sequence diagram.

    `key` — токен по которому ссылаются в сообщениях (alias или имя);
    `label` — то, что мы показываем в box-е (alias.target или имя).
    """

    key: str
    label: str


@dataclass(frozen=True)
class Message:
    src: str
    dst: str
    text: str
    arrow: ArrowKind


@dataclass(frozen=True)
class Note:
    """Note attached to one (left/right of) or two (over) participants."""

    side: NoteSide
    participants: tuple[str, ...]
    text: str


# Row entries — message or note. Порядок в `rows` == порядок появления
# в исходнике; visual layout рисует их сверху вниз.
Row = Message | Note


@dataclass
class Sequence:
    participants: dict[str, Participant] = field(default_factory=dict)
    rows: list[Row] = field(default_factory=list)


# ── parser ────────────────────────────────────────────────────────────────

# `participant Alice` / `participant Alice as A` (alias)
_PARTICIPANT_RE = re.compile(
    r"""
    ^\s*
    (?:participant|actor)\s+
    (?P<a>[A-Za-z_]\w*)
    (?:\s+as\s+(?P<b>.+?))?
    \s*$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Arrows we recognise. Order matters: more specific tokens первыми
# (`-->>` раньше `->>`, `-)` раньше `-`). Captures the arrow itself in
# group `arrow`. `:` отделяет text.
_MSG_RE = re.compile(
    r"""
    ^\s*
    (?P<src>[A-Za-z_]\w*)
    \s*
    (?P<arrow>-->>|->>|-->|-\)|->)
    \s*
    (?P<dst>[A-Za-z_]\w*)
    \s*:\s*
    (?P<text>.*)$
    """,
    re.VERBOSE,
)

# Notes: `Note over A,B: text`, `Note left of A: text`, `Note right of A: text`.
_NOTE_RE = re.compile(
    r"""
    ^\s*
    note\s+
    (?P<side>over|left\s+of|right\s+of)
    \s+
    (?P<who>[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)?)
    \s*:\s*
    (?P<text>.*)$
    """,
    re.VERBOSE | re.IGNORECASE,
)

# Block fences we silently skip: `loop … end`, `alt … end`, etc.
_BLOCK_OPEN_RE = re.compile(
    r"^\s*(?:loop|alt|par|opt|critical|break|rect)\b",
    re.IGNORECASE,
)
_BLOCK_BRANCH_RE = re.compile(
    r"^\s*(?:else|and|option)\b",
    re.IGNORECASE,
)
_BLOCK_END_RE = re.compile(r"^\s*end\s*$", re.IGNORECASE)

# Активации участников — пропускаем (без визуала пока).
_ACTIVATE_RE = re.compile(
    r"^\s*(?:activate|deactivate)\s+[A-Za-z_]\w*\s*$",
    re.IGNORECASE,
)


def _arrow_kind(arrow: str) -> ArrowKind:
    """Map raw arrow token to a coarse visual kind.

    `->>` solid head, `-->>` dashed (двойной head + пунктирный shaft),
    `-)` open async, `->` без явной стрелки → plain.
    """
    if arrow == "-->>":
        return "dashed"
    if arrow == "->>":
        return "solid"
    if arrow == "-)":
        return "open"
    if arrow == "->":
        return "plain"
    # `-->` fall-through (mermaid pre-2 syntax) — relax to dashed.
    return "dashed"


def _ensure_participant(seq: Sequence, key: str) -> None:
    """Add a participant if it wasn't declared explicitly.

    В Mermaid `participant` не обязателен — узлы можно использовать
    сразу в сообщении, порядок определяется первым упоминанием.
    """
    if key not in seq.participants:
        seq.participants[key] = Participant(key=key, label=key)


def parse_sequence(source: str) -> Sequence | None:
    """Parse *source* as a Mermaid sequenceDiagram.

    Returns None if the first significant line isn't `sequenceDiagram`.
    Malformed lines are silently skipped — модель может выдать мусор,
    мы возвращаем что насобирали.
    """
    if not source:
        return None
    lines = source.splitlines()

    # Header gate: первая значимая строка должна быть `sequenceDiagram`.
    header_seen = False
    for raw in lines:
        stripped = raw.strip()
        if not stripped or stripped.startswith("%%"):
            continue
        if stripped.lower().startswith("sequencediagram"):
            header_seen = True
        break
    if not header_seen:
        return None

    seq = Sequence()
    for raw in lines:
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("%%"):
            continue
        low = stripped.lower()
        if low.startswith("sequencediagram"):
            continue
        # Block fences / branches / end — silent skip, inner messages
        # рендерятся плоским потоком.
        if _BLOCK_OPEN_RE.match(stripped) or _BLOCK_BRANCH_RE.match(stripped):
            continue
        if _BLOCK_END_RE.match(stripped):
            continue
        if _ACTIVATE_RE.match(stripped):
            continue

        m = _PARTICIPANT_RE.match(stripped)
        if m:
            a = m.group("a")
            b = m.group("b")
            if b is not None:
                # `participant Alice as A` — key=A, label=Alice (alias
                # удобнее для коротких столбцов, оригинал — для глаз).
                seq.participants[b.strip()] = Participant(key=b.strip(), label=a.strip())
            else:
                _ensure_participant(seq, a)
            continue

        m = _NOTE_RE.match(stripped)
        if m:
            side_raw = m.group("side").lower().replace(" ", "")
            side: NoteSide = (
                "over" if side_raw == "over" else ("left" if side_raw == "leftof" else "right")
            )
            who = [p.strip() for p in m.group("who").split(",") if p.strip()]
            for w in who:
                _ensure_participant(seq, w)
            seq.rows.append(Note(side=side, participants=tuple(who), text=m.group("text").strip()))
            continue

        m = _MSG_RE.match(stripped)
        if m:
            src = m.group("src")
            dst = m.group("dst")
            _ensure_participant(seq, src)
            _ensure_participant(seq, dst)
            seq.rows.append(
                Message(
                    src=src,
                    dst=dst,
                    text=m.group("text").strip(),
                    arrow=_arrow_kind(m.group("arrow")),
                )
            )
            continue
        # Неизвестная строка — silent skip.

    return seq


# ── layout & render ───────────────────────────────────────────────────────

# Минимальная пустая полоса между колонками — должна вместить arrow
# с маркером (`---X--->`) и не давать боксам слипаться.
GUTTER = 4
# Минимальная "толщина" колонки. Для однобуквенных имён `A`/`B` без неё
# arrow-сегмент сжимается до 3 символов и текст не виден.
MIN_COL_W = 5
# Стартовое смещение слева, чтобы lifeline и box были видимыми.
LEFT_PAD = 0


def _participant_box(p: Participant) -> list[str]:
    """3-line box for a participant. Width = label + 2 borders.

    Без внутреннего паддинга — `|Alice|` короче и плотнее ставится в
    канвас; для коротких имён это критично, чтобы lifeline не уезжала.
    """
    inner = p.label
    inner_w = max(len(inner), 1)
    top = "+" + "-" * inner_w + "+"
    mid = "|" + inner + "|"
    bot = "+" + "-" * inner_w + "+"
    return [top, mid, bot]


def _box_width(p: Participant) -> int:
    return max(len(p.label), 1) + 2  # 2 borders, no padding


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


def _column_positions(
    participants: list[Participant],
) -> tuple[list[int], list[int], int]:
    """Compute left-edge, center-x and total-width for each column.

    Returns (left_edges, centers, total_width). Колонки разделены
    GUTTER пробелами между правым краем одной и левым краем следующей.
    Минимальная ширина колонки — MIN_COL_W; для коротких имён (`A` / `B`)
    это даёт стрелкам место под текст сообщения.
    """
    lefts = []
    centers = []
    pos = LEFT_PAD
    for p in participants:
        w = max(_box_width(p), MIN_COL_W)
        lefts.append(pos)
        centers.append(pos + w // 2)
        pos += w + GUTTER
    total = pos - GUTTER if participants else 0
    return lefts, centers, total


def _arrow_line(width: int, kind: ArrowKind, reverse: bool, text: str) -> str:
    """Build the arrow segment string `---text--->` of *width* chars.

    width — длина строки между центрами двух колонок (включая endpoints).
    reverse=True → стрелка указывает влево.

    Гарантия: для kind="dashed" хотя бы один `.` остаётся в выводе даже
    когда text занимает почти всю inner-область. Иначе пользователь не
    сможет визуально отличить solid от dashed.
    """
    if width < 3:
        return "-" * width
    fill = "." if kind == "dashed" else "-"
    head: str
    tail: str
    if reverse:
        head = "<" if kind in ("solid", "dashed", "plain") else "("
        tail = ""
    else:
        head = ""
        tail = ">" if kind in ("solid", "dashed", "plain") else ")"
    inner_w = width - 2
    # Зарезервируем по 1 fill-char с каждой стороны, чтобы dashed `.`
    # всегда оставался виден (иначе solid и dashed визуально неотличимы).
    min_fill_each_side = 1
    if text:
        # Усекаем text до того, что влезает с учётом реза под fill.
        max_text = max(
            inner_w - len(head) - len(tail) - 2 * min_fill_each_side - 2,
            0,
        )
        if len(text) > max_text:
            text = text[: max(max_text - 1, 1)] + "…"
        if text:
            text = f" {text} "
    pad_total = inner_w - len(text) - len(head) - len(tail)
    if pad_total < 2 * min_fill_each_side:
        # На совсем узких канвасах хотя бы одна fill-char на каждую
        # сторону выживает, иначе теряется визуальная сигнатура.
        pad_total = max(pad_total, 2)
    left_pad = max(pad_total // 2, min_fill_each_side)
    right_pad = max(pad_total - left_pad, min_fill_each_side)
    return "|" + head + fill * left_pad + text + fill * right_pad + tail + "|"


def _render_message(
    canvas: list[list[str]],
    msg: Message,
    row_y: int,
    key_to_idx: dict[str, int],
    centers: list[int],
    kind: ArrowKind,
) -> None:
    """Paint a single message line at *row_y*."""
    if msg.src not in key_to_idx or msg.dst not in key_to_idx:
        return
    si = key_to_idx[msg.src]
    di = key_to_idx[msg.dst]
    if si == di:
        # Self-message: рисуем как короткую заметку справа от lifeline.
        cx = centers[si]
        text = f"-> {msg.text}" if msg.text else "->"
        for i, ch in enumerate(text):
            _set(canvas, row_y, cx + 2 + i, ch)
        # Lifeline в этой строке тоже должен быть.
        _set(canvas, row_y, cx, "|")
        return
    reverse = di < si
    left_i, right_i = (di, si) if reverse else (si, di)
    cx_left = centers[left_i]
    cx_right = centers[right_i]
    width = cx_right - cx_left + 1
    line = _arrow_line(width, kind, reverse=reverse, text=msg.text)
    for i, ch in enumerate(line):
        col = cx_left + i
        _set(canvas, row_y, col, ch)


def _render_note(
    canvas: list[list[str]],
    note: Note,
    row_y: int,
    key_to_idx: dict[str, int],
    lefts: list[int],
    centers: list[int],
    widths: list[int],
) -> int:
    """Paint a note box; returns the row index just below the note.

    Note занимает 3 строки. Если span не помещается, рисуем минимальную
    коробку под левым участником. Возвращаем `row_y + 3`, чтобы caller
    подвинул дальнейшие сообщения.
    """
    targets = [k for k in note.participants if k in key_to_idx]
    if not targets:
        return row_y + 1
    if note.side == "over":
        if len(targets) == 1:
            i = key_to_idx[targets[0]]
            box_left = lefts[i]
            box_right = box_left + widths[i] - 1
        else:
            i = key_to_idx[targets[0]]
            j = key_to_idx[targets[-1]]
            if j < i:
                i, j = j, i
            box_left = lefts[i]
            box_right = lefts[j] + widths[j] - 1
    elif note.side == "left":
        i = key_to_idx[targets[0]]
        # Ставим box слева от участника. Минимум 6 ширины.
        text_w = max(len(note.text), 4)
        box_right = lefts[i] - 1
        box_left = max(0, box_right - (text_w + 3))
    else:  # right
        i = key_to_idx[targets[0]]
        text_w = max(len(note.text), 4)
        box_left = lefts[i] + widths[i] + 1
        box_right = box_left + text_w + 3
    inner_w = box_right - box_left - 1
    if inner_w < 1:
        inner_w = 1
    text = note.text
    if len(text) > inner_w - 2:
        text = text[: max(inner_w - 3, 1)] + "…"
    pad_total = inner_w - len(text) - 2
    if pad_total < 0:
        pad_total = 0
    body = " " + text + " " * (pad_total + 1)
    body = body[:inner_w]
    top = "+" + "-" * inner_w + "+"
    mid = "|" + body + "|"
    bot = "+" + "-" * inner_w + "+"
    for r, line in enumerate((top, mid, bot)):
        for c, ch in enumerate(line):
            if ch == " ":
                continue
            _set(canvas, row_y + r, box_left + c, ch)
    return row_y + 3


def _draw_lifelines(
    canvas: list[list[str]],
    centers: list[int],
    y_start: int,
    y_end: int,
) -> None:
    """Paint vertical `|` lifelines from y_start to y_end inclusive.

    Сообщения и notes, рисуемые поверх, перезаписывают lifeline в своих
    строках — это ок, визуальный приоритет за стрелкой.
    """
    for cx in centers:
        for y in range(y_start, y_end + 1):
            _set(canvas, y, cx, "|")


def render(seq: Sequence) -> str:
    """Render *seq* to a multi-line ASCII string.

    Layout:
    - 3-line header band: top/mid/bot of participant boxes.
    - one empty row gap.
    - rows: messages = 1 row each, notes = 3 rows each, each followed by
      one empty row to make lifelines breathe.
    - trailing empty + lifeline tick line at the bottom.
    """
    if not seq.participants:
        return ""
    participants = list(seq.participants.values())
    key_to_idx = {p.key: i for i, p in enumerate(participants)}
    lefts, centers, total_w = _column_positions(participants)
    widths = [_box_width(p) for p in participants]
    # Если есть self-message (src==dst) — резервируем справа от правого
    # участника достаточно места под `-> <text>`, иначе текст уезжает за
    # канвас и теряется.
    self_text_w = 0
    for row in seq.rows:
        if isinstance(row, Message) and row.src == row.dst:
            wanted = len(row.text) + 4  # "-> " + text + 1 padding
            if wanted > self_text_w:
                self_text_w = wanted
    if self_text_w:
        total_w += self_text_w

    # Pre-compute vertical positions: каждое message = 2 строки (gap+msg),
    # каждая note = 4 строки (gap+3 box). Считаем total_h заранее.
    header_h = 3
    rows_y: list[int] = []
    cursor = header_h + 1  # one blank row after header
    for row in seq.rows:
        rows_y.append(cursor)
        if isinstance(row, Note):
            cursor += 3 + 1  # note + blank
        else:
            cursor += 1 + 1  # message + blank
    bottom_pad = 1
    total_h = cursor + bottom_pad

    canvas: list[list[str]] = [[" "] * max(total_w, 1) for _ in range(total_h)]

    # Draw participant boxes at top.
    for i, p in enumerate(participants):
        _draw_box(canvas, _participant_box(p), 0, lefts[i])

    # Lifelines run from below the header to the bottom of the canvas.
    _draw_lifelines(canvas, centers, header_h, total_h - 1)

    # Now paint each row.
    for row, y in zip(seq.rows, rows_y, strict=True):
        if isinstance(row, Note):
            _render_note(canvas, row, y, key_to_idx, lefts, centers, widths)
        else:
            _render_message(canvas, row, y, key_to_idx, centers, row.arrow)

    return "\n".join("".join(r).rstrip() for r in canvas)


__all__ = [
    "Sequence",
    "Participant",
    "Message",
    "Note",
    "parse_sequence",
    "render",
]
