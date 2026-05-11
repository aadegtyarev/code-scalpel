"""Tests for the frozen value types in `code_scalpel.index.model`."""

from __future__ import annotations

import pytest

from code_scalpel.index.model import FileIndex, Symbol


def test_symbol_is_frozen() -> None:
    sym = Symbol(
        name="foo",
        kind="function",
        qualified_name="foo",
        lineno=1,
        end_lineno=3,
        docstring="",
    )
    with pytest.raises(AttributeError):
        sym.name = "bar"  # type: ignore[misc]


def test_file_index_is_frozen() -> None:
    idx = FileIndex(rel_path="x.py", symbols=(), imports=(), loc=0)
    with pytest.raises(AttributeError):
        idx.rel_path = "y.py"  # type: ignore[misc]


def test_symbol_holds_qualified_name_and_lines() -> None:
    sym = Symbol(
        name="bar",
        kind="method",
        qualified_name="Foo.bar",
        lineno=5,
        end_lineno=10,
        docstring="Do a thing.",
    )
    assert sym.qualified_name == "Foo.bar"
    assert sym.lineno == 5
    assert sym.end_lineno == 10
    assert sym.docstring == "Do a thing."


def test_file_index_tuples_are_immutable() -> None:
    idx = FileIndex(
        rel_path="x.py",
        symbols=(
            Symbol(
                name="f", kind="function", qualified_name="f", lineno=1, end_lineno=2, docstring=""
            ),
        ),
        imports=("pkg.mod",),
        loc=2,
    )
    assert isinstance(idx.symbols, tuple)
    assert isinstance(idx.imports, tuple)
    assert idx.loc == 2
