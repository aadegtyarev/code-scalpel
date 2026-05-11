"""Tests for the Mermaid sequenceDiagram parser & renderer.

Sequence: actors-as-columns layout, fundamentally different shape from
flowchart, поэтому отдельный файл. Parser должен глотать messages,
notes, alias-ы, и тихо пропускать loop/alt/par-блоки. Renderer проверяем
по устойчивым инвариантам — box-borders на месте, lifeline-pipes
непрерывны, текст сообщений виден.
"""

from __future__ import annotations

from code_scalpel.mermaid import render_mermaid
from code_scalpel.mermaid.sequence import (
    Message,
    Note,
    Participant,
    parse_sequence,
    render,
)

# ── parser tests ───────────────────────────────────────────────────────────


def test_header_required_returns_none_without() -> None:
    assert parse_sequence("Alice->>Bob: Hi") is None


def test_empty_source_returns_none() -> None:
    assert parse_sequence("") is None


def test_header_only_returns_empty_diagram() -> None:
    seq = parse_sequence("sequenceDiagram")
    assert seq is not None
    assert seq.participants == {}
    assert seq.rows == []


def test_participant_declaration() -> None:
    seq = parse_sequence("sequenceDiagram\nparticipant Alice")
    assert seq is not None
    assert "Alice" in seq.participants
    assert seq.participants["Alice"].label == "Alice"


def test_participant_with_alias() -> None:
    seq = parse_sequence("sequenceDiagram\nparticipant Alice as A")
    assert seq is not None
    assert "A" in seq.participants
    assert seq.participants["A"].label == "Alice"


def test_actor_is_treated_as_participant() -> None:
    seq = parse_sequence("sequenceDiagram\nactor Bob")
    assert seq is not None
    assert "Bob" in seq.participants


def test_implicit_participant_via_message() -> None:
    seq = parse_sequence("sequenceDiagram\nAlice->>Bob: Hi")
    assert seq is not None
    assert "Alice" in seq.participants
    assert "Bob" in seq.participants


def test_solid_double_arrow() -> None:
    seq = parse_sequence("sequenceDiagram\nA->>B: msg")
    assert seq is not None
    assert isinstance(seq.rows[0], Message)
    assert seq.rows[0].arrow == "solid"


def test_dashed_double_arrow() -> None:
    seq = parse_sequence("sequenceDiagram\nA-->>B: msg")
    assert seq is not None
    assert isinstance(seq.rows[0], Message)
    assert seq.rows[0].arrow == "dashed"


def test_plain_single_arrow() -> None:
    seq = parse_sequence("sequenceDiagram\nA->B: sync")
    assert seq is not None
    assert isinstance(seq.rows[0], Message)
    assert seq.rows[0].arrow == "plain"


def test_open_async_arrow() -> None:
    seq = parse_sequence("sequenceDiagram\nA-)B: async")
    assert seq is not None
    assert isinstance(seq.rows[0], Message)
    assert seq.rows[0].arrow == "open"


def test_note_over_two_participants() -> None:
    seq = parse_sequence("sequenceDiagram\nparticipant A\nparticipant B\nNote over A,B: shared")
    assert seq is not None
    notes = [r for r in seq.rows if isinstance(r, Note)]
    assert len(notes) == 1
    assert notes[0].side == "over"
    assert notes[0].participants == ("A", "B")
    assert notes[0].text == "shared"


def test_note_left_of() -> None:
    seq = parse_sequence("sequenceDiagram\nparticipant A\nNote left of A: hi")
    assert seq is not None
    notes = [r for r in seq.rows if isinstance(r, Note)]
    assert len(notes) == 1
    assert notes[0].side == "left"


def test_note_right_of() -> None:
    seq = parse_sequence("sequenceDiagram\nparticipant A\nNote right of A: hi")
    assert seq is not None
    notes = [r for r in seq.rows if isinstance(r, Note)]
    assert len(notes) == 1
    assert notes[0].side == "right"


def test_comments_skipped() -> None:
    seq = parse_sequence("sequenceDiagram\n%% a comment\nA->>B: hi")
    assert seq is not None
    assert len(seq.rows) == 1


def test_loop_block_inner_messages_flat() -> None:
    """loop ... end — fence игнорируется, внутренние сообщения остаются."""
    src = (
        "sequenceDiagram\n"
        "A->>B: outside\n"
        "loop every minute\n"
        "  A->>B: inside\n"
        "end\n"
        "A->>B: also outside\n"
    )
    seq = parse_sequence(src)
    assert seq is not None
    msgs = [r for r in seq.rows if isinstance(r, Message)]
    assert len(msgs) == 3


def test_alt_else_block_inner_messages_flat() -> None:
    src = "sequenceDiagram\nalt ok\n  A->>B: yes\nelse not ok\n  A->>B: no\nend\n"
    seq = parse_sequence(src)
    assert seq is not None
    msgs = [r for r in seq.rows if isinstance(r, Message)]
    assert len(msgs) == 2


def test_par_block_inner_messages_flat() -> None:
    src = "sequenceDiagram\npar task1\n  A->>B: a\nand task2\n  A->>B: b\nend\n"
    seq = parse_sequence(src)
    assert seq is not None
    msgs = [r for r in seq.rows if isinstance(r, Message)]
    assert len(msgs) == 2


def test_opt_block_inner_messages_flat() -> None:
    src = "sequenceDiagram\nopt maybe\n  A->>B: hi\nend\n"
    seq = parse_sequence(src)
    assert seq is not None
    msgs = [r for r in seq.rows if isinstance(r, Message)]
    assert len(msgs) == 1


def test_activate_deactivate_silently_skipped() -> None:
    src = "sequenceDiagram\nparticipant A\nactivate A\nA->>B: hi\ndeactivate A\n"
    seq = parse_sequence(src)
    assert seq is not None
    # Один message, никаких заметок про активацию.
    assert len([r for r in seq.rows if isinstance(r, Message)]) == 1


def test_malformed_line_skipped() -> None:
    src = "sequenceDiagram\n!!! garbage !!!\nA->>B: hi\n"
    seq = parse_sequence(src)
    assert seq is not None
    assert len([r for r in seq.rows if isinstance(r, Message)]) == 1


# ── render tests ──────────────────────────────────────────────────────────


def test_render_two_actor_handshake_basic_shape() -> None:
    out = render_mermaid("sequenceDiagram\nAlice->>Bob: Hi\nBob-->>Alice: Hey")
    assert out is not None
    # Box borders для обоих participants.
    assert "+-----+" in out  # Alice (5 chars)
    assert "+---+" in out  # Bob (3 chars)
    assert "|Alice|" in out
    assert "|Bob|" in out
    # Message text.
    assert "Hi" in out
    assert "Hey" in out
    # Arrow heads видно: `>` для solid, `<` для reverse.
    assert ">" in out
    assert "<" in out
    # Lifelines — vertical pipes.
    assert "|" in out


def test_render_alias_label_used() -> None:
    out = render_mermaid("sequenceDiagram\nparticipant Alice as A\nA->>A: self")
    assert out is not None
    assert "|Alice|" in out
    # Self-message — короткая стрелочка-нотация рядом с lifeline.
    assert "self" in out


def test_render_note_box_present() -> None:
    out = render_mermaid("sequenceDiagram\nparticipant A\nparticipant B\nNote over A,B: shared")
    assert out is not None
    # Note рисуется как +---+ box со словом внутри.
    assert "shared" in out
    # Над диаграммой присутствуют и participant boxes, и note box.
    assert out.count("+") >= 6  # 2 corners × 2 participants × 2 + note corners


def test_render_dashed_arrow_uses_different_glyph() -> None:
    out = render_mermaid("sequenceDiagram\nA->>B: solid\nB-->>A: dashed")
    assert out is not None
    # Solid line uses `-`; dashed uses `.`. Оба видны в выводе.
    assert "-" in out
    assert "." in out


def test_render_empty_diagram_returns_empty_string() -> None:
    # `sequenceDiagram` без участников — рендер пустой.
    assert render_mermaid("sequenceDiagram") == ""


def test_render_dispatch_via_first_significant_line() -> None:
    """Лидирующие комментарии не сбивают dispatch."""
    out = render_mermaid("%% a comment\nsequenceDiagram\nA->>B: hi")
    assert out is not None
    assert "hi" in out


def test_render_self_message_does_not_crash() -> None:
    out = render_mermaid("sequenceDiagram\nA->>A: think")
    assert out is not None
    assert "think" in out


def test_render_long_text_truncated() -> None:
    out = render_mermaid("sequenceDiagram\nA->>B: " + "x" * 80)
    assert out is not None
    # Длина строки ограничена шириной между двумя колонками — не уехала
    # на 80+ символов.
    longest = max(len(line) for line in out.splitlines())
    assert longest < 80


def test_participant_object_round_trip() -> None:
    p = Participant(key="K", label="Lbl")
    assert p.key == "K" and p.label == "Lbl"


def test_render_function_directly_with_empty_returns_empty() -> None:
    from code_scalpel.mermaid.sequence import Sequence

    assert render(Sequence()) == ""
