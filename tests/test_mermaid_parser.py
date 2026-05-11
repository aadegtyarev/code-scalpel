"""Tests for the Mermaid flowchart parser.

Парсер должен быть толерантным: модель может выдать любой мусор,
TUI не должен падать. Проверяем каждую форму узла, каждый тип
стрелки, корректное завершение на non-flowchart, и тихий skip
неузнаваемых строк.
"""

from __future__ import annotations

from code_scalpel.mermaid.parser import parse_flowchart


def test_direction_td() -> None:
    fc = parse_flowchart("flowchart TD\nA --> B")
    assert fc is not None
    assert fc.direction == "TD"


def test_direction_lr() -> None:
    fc = parse_flowchart("flowchart LR\nA --> B")
    assert fc is not None
    assert fc.direction == "LR"


def test_direction_tb_aliases_td() -> None:
    fc = parse_flowchart("flowchart TB\nA --> B")
    assert fc is not None
    assert fc.direction == "TD"


def test_graph_keyword_accepted() -> None:
    fc = parse_flowchart("graph TD\nA --> B")
    assert fc is not None
    assert fc.direction == "TD"
    assert "A" in fc.nodes
    assert "B" in fc.nodes


def test_default_direction_when_missing() -> None:
    fc = parse_flowchart("A --> B")
    assert fc is not None
    assert fc.direction == "TD"


def test_rect_shape_default() -> None:
    fc = parse_flowchart("flowchart TD\nA[Hello]")
    assert fc is not None
    assert fc.nodes["A"].shape == "rect"
    assert fc.nodes["A"].label == "Hello"


def test_round_shape() -> None:
    fc = parse_flowchart("flowchart TD\nA(Hello)")
    assert fc is not None
    assert fc.nodes["A"].shape == "round"
    assert fc.nodes["A"].label == "Hello"


def test_diamond_shape() -> None:
    fc = parse_flowchart("flowchart TD\nA{Choose}")
    assert fc is not None
    assert fc.nodes["A"].shape == "diamond"
    assert fc.nodes["A"].label == "Choose"


def test_subroutine_shape() -> None:
    fc = parse_flowchart("flowchart TD\nA[[Helper]]")
    assert fc is not None
    assert fc.nodes["A"].shape == "subroutine"
    assert fc.nodes["A"].label == "Helper"


def test_bare_id_label_equals_id() -> None:
    fc = parse_flowchart("flowchart TD\nA --> B")
    assert fc is not None
    assert fc.nodes["A"].label == "A"
    assert fc.nodes["A"].shape == "rect"


def test_quoted_label_with_brackets() -> None:
    fc = parse_flowchart('flowchart TD\nA["Label with [brackets]"]')
    assert fc is not None
    assert fc.nodes["A"].label == "Label with [brackets]"


def test_edge_solid_arrow() -> None:
    fc = parse_flowchart("flowchart TD\nA --> B")
    assert fc is not None
    assert len(fc.edges) == 1
    assert fc.edges[0].from_id == "A"
    assert fc.edges[0].to_id == "B"
    assert fc.edges[0].label is None


def test_edge_with_label() -> None:
    fc = parse_flowchart("flowchart TD\nA -->|yes| B")
    assert fc is not None
    assert fc.edges[0].label == "yes"


def test_edge_no_arrow() -> None:
    fc = parse_flowchart("flowchart TD\nA --- B")
    assert fc is not None
    assert len(fc.edges) == 1


def test_edge_dotted() -> None:
    fc = parse_flowchart("flowchart TD\nA -.-> B")
    assert fc is not None
    assert len(fc.edges) == 1


def test_edge_thick() -> None:
    fc = parse_flowchart("flowchart TD\nA ==> B")
    assert fc is not None
    assert len(fc.edges) == 1


def test_comments_skipped() -> None:
    fc = parse_flowchart("flowchart TD\n%% this is a comment\nA --> B")
    assert fc is not None
    assert len(fc.edges) == 1


def test_malformed_line_skipped_not_raised() -> None:
    fc = parse_flowchart("flowchart TD\nA --> B\nthis is garbage 12345 !! @@\nB --> C\n")
    assert fc is not None
    assert len(fc.edges) == 2


def test_sequence_diagram_returns_none() -> None:
    fc = parse_flowchart("sequenceDiagram\nAlice->>John: Hello")
    assert fc is None


def test_class_diagram_returns_none() -> None:
    fc = parse_flowchart("classDiagram\nAnimal <|-- Duck")
    assert fc is None


def test_gantt_returns_none() -> None:
    fc = parse_flowchart("gantt\ntitle Foo")
    assert fc is None


def test_empty_body_returns_empty_flowchart() -> None:
    fc = parse_flowchart("flowchart TD\n")
    assert fc is not None
    assert fc.nodes == {}
    assert fc.edges == []


def test_empty_string_returns_empty_flowchart() -> None:
    fc = parse_flowchart("")
    assert fc is not None
    assert fc.nodes == {}


def test_subgraph_block_does_not_crash() -> None:
    src = "flowchart TD\nsubgraph foo\n  A --> B\nend\nB --> C\n"
    fc = parse_flowchart(src)
    assert fc is not None
    # Внутренние рёбра парсятся, subgraph fence игнорируется.
    assert len(fc.edges) >= 2


def test_inline_shape_in_edge() -> None:
    """`A[Hello] --> B[World]` — узлы декларируются прямо в edge-строке."""
    fc = parse_flowchart("flowchart TD\nA[Hello] --> B[World]")
    assert fc is not None
    assert fc.nodes["A"].label == "Hello"
    assert fc.nodes["B"].label == "World"
