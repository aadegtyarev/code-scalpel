"""Tests for `code_scalpel.workspace.internal_packages`.

Both the project map (for import filtering) and the tree-sitter index
(for the same reason) call this. The contract: a name is internal iff
it's a package dir with `__init__.py` directly under root, OR a bare
`*.py` at the root.
"""

from __future__ import annotations

from pathlib import Path

from code_scalpel.workspace import internal_packages


def test_package_dir_with_init_is_internal(tmp_path: Path) -> None:
    """The standard layout — `code_scalpel/__init__.py` makes the package
    name (`code_scalpel`) internal."""
    (tmp_path / "mypkg").mkdir()
    (tmp_path / "mypkg" / "__init__.py").write_text("")
    assert "mypkg" in internal_packages(tmp_path)


def test_bare_py_at_root_is_internal(tmp_path: Path) -> None:
    """Single-file projects: `tool.py` is its own namespace, importable
    as `tool` from anywhere else in the project."""
    (tmp_path / "tool.py").write_text("x = 1\n")
    assert "tool" in internal_packages(tmp_path)


def test_hidden_dirs_ignored(tmp_path: Path) -> None:
    """`.git`, `.venv` — hidden dirs almost never have `__init__.py`, so
    they fall out naturally. We assert that even if a hidden dir somehow
    had one, we treat it the same as any other dir (the filter is the
    `__init__.py` check, not a name pattern); but the realistic case —
    `.git/` without `__init__.py` — is what users actually hit."""
    (tmp_path / ".git").mkdir()
    (tmp_path / ".venv").mkdir()
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "__init__.py").write_text("")
    names = internal_packages(tmp_path)
    assert ".git" not in names
    assert ".venv" not in names
    assert "src" in names


def test_dir_without_init_skipped(tmp_path: Path) -> None:
    """A plain directory without `__init__.py` is not an importable
    package. Without this gate, `tests/` would show up as "internal" and
    every `from tests.something import` would surface in the MAP."""
    (tmp_path / "fixtures").mkdir()
    (tmp_path / "fixtures" / "data.txt").write_text("hi\n")
    assert "fixtures" not in internal_packages(tmp_path)


def test_dunder_init_at_root_not_listed(tmp_path: Path) -> None:
    """`__init__.py` at the root (rare but possible) isn't a name — it's
    just metadata for the parent. Filter it out explicitly."""
    (tmp_path / "__init__.py").write_text("")
    (tmp_path / "real.py").write_text("x = 1\n")
    names = internal_packages(tmp_path)
    assert "__init__" not in names
    assert "real" in names
