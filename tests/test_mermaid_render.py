"""Tests for the ASCII renderer.

Не пытаемся pixel-perfect-сравнить вывод — он чувствителен к выбору
gutter-констант. Проверяем устойчивые инварианты: характерные символы
формы (+---+, < >), наличие vertical/horizontal arrow-связи, и факт
что метка рёбра попала в финальный текст."""

from __future__ import annotations

from code_scalpel.mermaid import render_mermaid


def test_rect_box_characters_present() -> None:
    out = render_mermaid("flowchart TD\nA --> B")
    assert out is not None
    assert "+---+" in out
    # Both labels visible.
    assert " A " in out
    assert " B " in out


def test_vertical_arrow_between_td_boxes() -> None:
    out = render_mermaid("flowchart TD\nA --> B")
    assert out is not None
    # `|` vertical line and `v` arrowhead должны присутствовать.
    assert "|" in out
    assert "v" in out


def test_horizontal_arrow_between_lr_boxes() -> None:
    out = render_mermaid("flowchart LR\nA --> B")
    assert out is not None
    assert "---" in out  # горизонтальный сегмент
    assert ">" in out


def test_diamond_shape_rendered() -> None:
    out = render_mermaid("flowchart TD\nA{Decide} --> B")
    assert out is not None
    # Diamond ставим как < label > — оба символа в выводе.
    assert "<" in out
    assert ">" in out
    assert "Decide" in out


def test_round_shape_rendered() -> None:
    out = render_mermaid("flowchart TD\nA(Hello) --> B")
    assert out is not None
    # `( label )` — характерные круглые скобки в выводе.
    assert "(" in out
    assert ")" in out
    assert "Hello" in out


def test_edge_label_appears() -> None:
    out = render_mermaid("flowchart TD\nA -->|yes| B")
    assert out is not None
    assert "yes" in out


def test_linear_chain_renders_three_boxes() -> None:
    out = render_mermaid("flowchart TD\nA --> B\nB --> C")
    assert out is not None
    assert out.count("+---+") >= 3 * 2  # 3 boxes × top+bot border


def test_empty_flowchart_returns_empty_string() -> None:
    out = render_mermaid("flowchart TD")
    assert out == ""


def test_long_label_truncated_but_does_not_break() -> None:
    """Очень длинный label усекается до cap — рендер не падает."""
    src = "flowchart TD\nA[" + "x" * 100 + "] --> B"
    out = render_mermaid(src)
    assert out is not None
    # Бокс должен быть конечной ширины (cap), а не 100+.
    longest_line = max(len(line) for line in out.splitlines())
    assert longest_line < 60
