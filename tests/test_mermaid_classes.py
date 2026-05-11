"""Tests for the Mermaid classDiagram parser & renderer.

Class diagram переиспользует ту же rank-based-идею, что и flowchart, но
с трёхсекционными box-ами (name / fields / methods) и разными head
glyph'ами под каждый тип отношения.
"""

from __future__ import annotations

from code_scalpel.mermaid import render_mermaid
from code_scalpel.mermaid.classes import (
    parse_classes,
    render_classes,
)

# ── parser tests ───────────────────────────────────────────────────────────


def test_header_required_returns_none_without() -> None:
    assert parse_classes("Animal <|-- Duck") is None


def test_empty_source_returns_none() -> None:
    assert parse_classes("") is None


def test_header_only_returns_empty_diagram() -> None:
    diag = parse_classes("classDiagram")
    assert diag is not None
    assert diag.nodes == {}
    assert diag.relations == []


def test_bare_class_declaration() -> None:
    diag = parse_classes("classDiagram\nclass Animal")
    assert diag is not None
    assert "Animal" in diag.nodes
    assert diag.nodes["Animal"].fields == []
    assert diag.nodes["Animal"].methods == []


def test_inline_class_body_with_field_and_method() -> None:
    diag = parse_classes("classDiagram\nclass Animal {+int age; +run();}")
    assert diag is not None
    a = diag.nodes["Animal"]
    assert len(a.fields) == 1
    assert a.fields[0].text == "int age"
    assert a.fields[0].visibility == "+"
    assert len(a.methods) == 1
    assert a.methods[0].text == "run()"


def test_block_class_body_multiline() -> None:
    src = "classDiagram\nclass Animal {\n  +int age\n  +run()\n}"
    diag = parse_classes(src)
    assert diag is not None
    a = diag.nodes["Animal"]
    assert len(a.fields) == 1
    assert len(a.methods) == 1


def test_visibility_public_prefix() -> None:
    diag = parse_classes("classDiagram\nclass A { +pub }")
    assert diag is not None
    assert diag.nodes["A"].fields[0].visibility == "+"


def test_visibility_private_prefix() -> None:
    diag = parse_classes("classDiagram\nclass A { -priv }")
    assert diag is not None
    assert diag.nodes["A"].fields[0].visibility == "-"


def test_visibility_protected_prefix() -> None:
    diag = parse_classes("classDiagram\nclass A { #prot }")
    assert diag is not None
    assert diag.nodes["A"].fields[0].visibility == "#"


def test_visibility_package_prefix() -> None:
    diag = parse_classes("classDiagram\nclass A { ~pkg }")
    assert diag is not None
    assert diag.nodes["A"].fields[0].visibility == "~"


def test_method_detected_by_trailing_parens() -> None:
    diag = parse_classes("classDiagram\nclass A { +run() }")
    assert diag is not None
    a = diag.nodes["A"]
    assert a.methods and not a.fields
    assert a.methods[0].is_method


def test_relation_inheritance() -> None:
    diag = parse_classes("classDiagram\nAnimal <|-- Duck")
    assert diag is not None
    assert len(diag.relations) == 1
    rel = diag.relations[0]
    assert rel.kind == "inheritance"
    assert rel.src == "Animal"
    assert rel.dst == "Duck"


def test_relation_composition() -> None:
    diag = parse_classes("classDiagram\nContainer *-- Item")
    assert diag is not None
    assert diag.relations[0].kind == "composition"


def test_relation_aggregation() -> None:
    diag = parse_classes("classDiagram\nOwner o-- Asset")
    assert diag is not None
    assert diag.relations[0].kind == "aggregation"


def test_relation_association() -> None:
    diag = parse_classes("classDiagram\nA --> B")
    assert diag is not None
    assert diag.relations[0].kind == "association"


def test_relation_dependency() -> None:
    diag = parse_classes("classDiagram\nA ..> B")
    assert diag is not None
    assert diag.relations[0].kind == "dependency"


def test_relation_undirected() -> None:
    diag = parse_classes("classDiagram\nA -- B")
    assert diag is not None
    assert diag.relations[0].kind == "undirected"


def test_relation_with_label() -> None:
    diag = parse_classes("classDiagram\nA --> B : creates")
    assert diag is not None
    assert diag.relations[0].label == "creates"


def test_annotation_stripped() -> None:
    diag = parse_classes("classDiagram\nclass A {\n  <<interface>>\n  +do()\n}")
    assert diag is not None
    # `<<interface>>` строка — out of scope, methods остались.
    assert len(diag.nodes["A"].methods) == 1


def test_comments_skipped() -> None:
    diag = parse_classes("classDiagram\n%% top comment\nclass A")
    assert diag is not None
    assert "A" in diag.nodes


def test_reverse_inheritance_normalised() -> None:
    """`Duck --|> Animal` должен класть Animal как parent (src=Animal)."""
    diag = parse_classes("classDiagram\nDuck --|> Animal")
    assert diag is not None
    rel = diag.relations[0]
    assert rel.kind == "inheritance"
    assert rel.src == "Animal"
    assert rel.dst == "Duck"


def test_colon_member_syntax() -> None:
    """Альтернативный синтаксис `ClassName : +member` без `{}`."""
    diag = parse_classes("classDiagram\nclass A\nA : +run()")
    assert diag is not None
    assert len(diag.nodes["A"].methods) == 1


# ── render tests ──────────────────────────────────────────────────────────


def test_render_simple_inheritance_has_both_boxes_and_triangle() -> None:
    out = render_mermaid(
        "classDiagram\nclass Animal {+run()}\nclass Duck {+swim()}\nAnimal <|-- Duck"
    )
    assert out is not None
    # Имена классов и members видны.
    assert "Animal" in out
    assert "Duck" in out
    assert "+run()" in out
    assert "+swim()" in out
    # Triangle proxy: `/\` rendered как два символа.
    assert "/" in out
    assert "\\" in out
    # Box borders.
    assert "+---" in out


def test_render_three_section_box_for_class_with_fields_and_methods() -> None:
    out = render_mermaid("classDiagram\nclass A {\n  +int x\n  +run()\n}")
    assert out is not None
    # Имя, поле, метод.
    assert " A " in out
    assert "+int x" in out
    assert "+run()" in out
    # Делитель между секциями — лишний `+---+` сверху/снизу.
    # У ровно одного класса с обоими секциями должно быть 4 разделителя
    # (top, after-name, between-sections, bottom).
    assert out.count("+") >= 8


def test_render_class_with_only_methods_no_field_divider() -> None:
    out = render_mermaid("classDiagram\nclass A {+go()}")
    assert out is not None
    assert "+go()" in out


def test_render_class_without_members_compact() -> None:
    out = render_mermaid("classDiagram\nclass A")
    assert out is not None
    # Box с одним именем — 3 строки высотой.
    lines = [line for line in out.splitlines() if line.strip()]
    # Минимум top, name, bot.
    assert len(lines) >= 3


def test_render_composition_uses_diamond_marker() -> None:
    out = render_mermaid("classDiagram\nclass C\nclass I\nC *-- I")
    assert out is not None
    # Composition: `<>*` glyph.
    assert "<" in out
    assert ">" in out
    assert "*" in out


def test_render_aggregation_uses_open_diamond_marker() -> None:
    out = render_mermaid("classDiagram\nclass O\nclass A\nO o-- A")
    assert out is not None
    assert "<" in out
    assert ">" in out
    assert "o" in out


def test_render_association_arrowhead() -> None:
    out = render_mermaid("classDiagram\nclass A\nclass B\nA --> B")
    assert out is not None
    # Association — arrow head виден. Без иерархических edge'й оба
    # класса в одном ранге, поэтому стрелка горизонтальная (`>`), а
    # не вертикальная (`v` / `^`).
    assert ">" in out or "v" in out or "^" in out


def test_render_dependency_uses_dotted_shaft() -> None:
    out = render_mermaid("classDiagram\nclass A\nclass B\nA ..> B")
    assert out is not None
    # Dependency: dotted shaft → `.` symbol.
    assert "." in out


def test_render_dispatch_with_leading_comment() -> None:
    out = render_mermaid("%% header comment\nclassDiagram\nclass A")
    assert out is not None
    assert "A" in out


def test_render_relation_label_appears() -> None:
    out = render_mermaid("classDiagram\nclass A\nclass B\nA --> B : creates")
    assert out is not None
    assert "creates" in out


def test_render_empty_classdiagram_returns_empty_string() -> None:
    assert render_mermaid("classDiagram") == ""


def test_render_classes_directly_empty() -> None:
    from code_scalpel.mermaid.classes import ClassDiagram

    assert render_classes(ClassDiagram()) == ""


def test_render_long_member_truncated_no_canvas_overflow() -> None:
    out = render_mermaid("classDiagram\nclass A { +" + "x" * 100 + " }")
    assert out is not None
    longest = max(len(line) for line in out.splitlines())
    # Per-column width capped at 32 → строка не должна быть длиннее.
    assert longest < 40
