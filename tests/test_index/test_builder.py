"""Tests for `code_scalpel.index.builder.build_file_index`."""

from __future__ import annotations

import textwrap
from pathlib import Path

from code_scalpel.index.builder import build_file_index


def test_build_returns_none_for_missing_file(tmp_path: Path) -> None:
    assert build_file_index(tmp_path, "nope.py") is None


def test_build_returns_none_for_non_python(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("hello\nworld\n")
    assert build_file_index(tmp_path, "README.md") is None


def test_build_real_file(tmp_path: Path) -> None:
    # Make root look like a project so internal-package detection picks up
    # `pkg` as internal — that way the `from pkg.x import y` import surfaces.
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    (tmp_path / "pkg" / "mod.py").write_text(
        textwrap.dedent('''\
            """Module."""
            from pkg.other import Thing
            import os

            class Foo:
                """Foo doc."""
                def bar(self):
                    pass

            async def top():
                """Top doc."""
                return 1
            ''')
    )
    idx = build_file_index(tmp_path, "pkg/mod.py")
    assert idx is not None
    assert idx.rel_path == "pkg/mod.py"
    assert idx.loc > 0
    by_qn = {s.qualified_name: s for s in idx.symbols}
    assert by_qn["Foo"].kind == "class"
    assert by_qn["Foo"].docstring == "Foo doc."
    assert by_qn["Foo.bar"].kind == "method"
    assert by_qn["top"].kind == "async_function"
    # Internal imports surfaced, stdlib dropped
    assert "pkg.other.Thing" in idx.imports
    assert all(imp != "os" for imp in idx.imports)


def test_build_handles_syntax_error(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def foo(\n")
    idx = build_file_index(tmp_path, "broken.py")
    assert idx is not None
    # Empty symbols are fine — what matters is no exception was raised
    assert isinstance(idx.symbols, tuple)


def test_loc_counts_lines(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a = 1\nb = 2\nc = 3\n")
    idx = build_file_index(tmp_path, "f.py")
    assert idx is not None
    assert idx.loc == 3


def test_loc_counts_unterminated_last_line(tmp_path: Path) -> None:
    (tmp_path / "f.py").write_text("a = 1\nb = 2")
    idx = build_file_index(tmp_path, "f.py")
    assert idx is not None
    assert idx.loc == 2


def test_internal_packages_detect_bare_module(tmp_path: Path) -> None:
    # Single-file project: `foo.py` at root is its own internal namespace.
    (tmp_path / "foo.py").write_text("x = 1\n")
    (tmp_path / "bar.py").write_text("from foo import x\n")
    idx = build_file_index(tmp_path, "bar.py")
    assert idx is not None
    assert "foo.x" in idx.imports
