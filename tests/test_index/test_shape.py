"""Tests for `code_scalpel.index.shape.control_flow_shape`."""

from __future__ import annotations

import textwrap

from code_scalpel.index.shape import control_flow_shape


def _shape(src: str) -> dict[str, int]:
    return control_flow_shape(src.encode("utf-8"))


def test_empty_source_returns_zeros() -> None:
    counts = _shape("")
    assert counts == {"try": 0, "loops": 0, "if": 0, "raise": 0}


def test_counts_all_constructs() -> None:
    src = textwrap.dedent("""\
        def f():
            try:
                x = 1
            except Exception:
                raise

            for x in []:
                pass

            while True:
                break

            if True:
                pass

            squares = [x*x for x in range(10)]
        """)
    counts = _shape(src)
    assert counts["try"] == 1
    assert counts["raise"] == 1
    assert counts["if"] == 1
    # for + while + list_comprehension = 3
    assert counts["loops"] == 3


def test_counts_recurse_inside_classes_and_functions() -> None:
    src = textwrap.dedent("""\
        class Foo:
            def bar(self):
                if x:
                    if y:
                        pass
                for i in []:
                    raise ValueError
        """)
    counts = _shape(src)
    assert counts["if"] == 2
    assert counts["loops"] == 1
    assert counts["raise"] == 1


def test_syntax_error_is_tolerated() -> None:
    counts = _shape("def foo(\n    if True:\n        pass\n")
    assert isinstance(counts, dict)
    assert set(counts) == {"try", "loops", "if", "raise"}
