"""End-to-end tests for `render_mermaid` — the public entry point."""

from __future__ import annotations

from code_scalpel.mermaid import render_mermaid


def test_simple_flowchart_renders_to_non_empty_string() -> None:
    out = render_mermaid("flowchart TD\nA --> B")
    assert out is not None
    assert "A" in out
    assert "B" in out
    assert len(out) > 0


def test_sequence_diagram_now_renders() -> None:
    """Sequence renderer landed — `render_mermaid` отдаёт ASCII вместо None."""
    src = "sequenceDiagram\nAlice->>John: Hello\nJohn-->>Alice: Hi"
    out = render_mermaid(src)
    assert out is not None
    assert "Alice" in out
    assert "John" in out
    assert "Hello" in out


def test_classdiagram_now_renders() -> None:
    """Class renderer landed — `render_mermaid` отдаёт ASCII вместо None."""
    out = render_mermaid("classDiagram\nAnimal <|-- Duck")
    assert out is not None
    assert "Animal" in out
    assert "Duck" in out


def test_gantt_still_returns_none() -> None:
    """Не-flowchart, не-sequence, не-class → None как и было."""
    assert render_mermaid("gantt\ntitle Foo") is None


def test_renderer_does_not_raise_on_malformed_source() -> None:
    """Model garbage — мы возвращаем что есть, не падаем."""
    src = "flowchart TD\n!!!garbage!!!\nA --> B\n??? more nonsense\nB --> C"
    out = render_mermaid(src)
    assert out is not None
    assert "A" in out
    assert "B" in out
    assert "C" in out


def test_complex_diagram_with_diamond_and_labels() -> None:
    src = (
        "flowchart TD\n"
        "Start[Start] --> Check{OK?}\n"
        "Check -->|yes| Done[End]\n"
        "Check -->|no| Fail[Bail]\n"
    )
    out = render_mermaid(src)
    assert out is not None
    assert "Start" in out
    assert "OK?" in out
    assert "yes" in out
    assert "no" in out
    assert "Bail" in out
    # Diamond опознаётся по `<` `>`
    assert "<" in out
    assert ">" in out


def test_lr_direction_renders_horizontally() -> None:
    out = render_mermaid("flowchart LR\nA --> B")
    assert out is not None
    # Боксы рядом на одной строке: правый край A и левый край B
    # должны быть на одной строке вывода.
    lines = out.splitlines()
    assert any("+---+" in line and line.count("+---+") >= 2 for line in lines)
