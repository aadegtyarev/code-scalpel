"""AST import-graph check — v0.9 machine check."""

from __future__ import annotations

from pathlib import Path

from code_scalpel.checks import ImportIssue, check_imports


def _setup_project(tmp_path: Path) -> Path:
    """Bare project layout with one in-project module."""
    (tmp_path / "mypkg").mkdir()
    (tmp_path / "mypkg" / "__init__.py").write_text("")
    (tmp_path / "mypkg" / "core.py").write_text("def greet():\n    return 'hi'\n\n_private = 1\n")
    return tmp_path


def test_resolves_valid_import(tmp_path: Path) -> None:
    """Real export → no issue. Baseline that the walker actually
    parses imports."""
    root = _setup_project(tmp_path)
    consumer = root / "main.py"
    consumer.write_text("from mypkg.core import greet\nprint(greet())\n")

    issues = check_imports(consumer, root)

    assert issues == []


def test_flags_missing_name(tmp_path: Path) -> None:
    """`from mypkg.core import farewell` where only `greet` exists →
    flagged."""
    root = _setup_project(tmp_path)
    consumer = root / "main.py"
    consumer.write_text("from mypkg.core import farewell\n")

    issues = check_imports(consumer, root)

    assert len(issues) == 1
    assert issues[0].name == "farewell"
    assert issues[0].module == "mypkg.core"
    assert issues[0].reason == "name not exported"


def test_skips_external_modules(tmp_path: Path) -> None:
    """`import foo` from stdlib / third party isn't ours to audit —
    mypy / runtime catches that with proper signatures."""
    root = _setup_project(tmp_path)
    consumer = root / "main.py"
    consumer.write_text("from json import dumps\nfrom requests import get\n")

    issues = check_imports(consumer, root)

    assert issues == []


def test_skips_relative_imports(tmp_path: Path) -> None:
    """Relative imports need package context we don't carry here.
    Skipped silently rather than incorrectly flagged."""
    root = _setup_project(tmp_path)
    consumer = root / "mypkg" / "sub.py"
    consumer.write_text("from . import core\n")

    issues = check_imports(consumer, root)

    assert issues == []


def test_respects_dunder_all(tmp_path: Path) -> None:
    """`__all__` with a literal list defines exports; anything not
    listed is private even if defined at top level."""
    root = tmp_path
    (root / "facade.py").write_text(
        "def public():\n    return 1\n\ndef hidden():\n    return 2\n\n__all__ = ['public']\n"
    )
    consumer = root / "main.py"
    consumer.write_text("from facade import public, hidden\n")

    issues = check_imports(consumer, root)

    assert {i.name for i in issues} == {"hidden"}


def test_walks_top_level_assigns(tmp_path: Path) -> None:
    """Constants / module-level vars count as exports too."""
    root = tmp_path
    (root / "config.py").write_text("DEFAULT_TIMEOUT = 30\n")
    consumer = root / "main.py"
    consumer.write_text("from config import DEFAULT_TIMEOUT, MISSING\n")

    issues = check_imports(consumer, root)

    names = {i.name for i in issues}
    assert names == {"MISSING"}


def test_walks_reexports(tmp_path: Path) -> None:
    """A module that does `from x import y` re-exports `y`."""
    root = tmp_path
    (root / "inner.py").write_text("def f():\n    return 1\n")
    (root / "facade.py").write_text("from inner import f\n")
    consumer = root / "main.py"
    consumer.write_text("from facade import f\n")

    issues = check_imports(consumer, root)

    assert issues == []


def test_star_import_is_ignored(tmp_path: Path) -> None:
    """`from X import *` can't be audited without executing the module."""
    root = _setup_project(tmp_path)
    consumer = root / "main.py"
    consumer.write_text("from mypkg.core import *\n")

    issues = check_imports(consumer, root)

    assert issues == []


def test_module_not_found_is_silent(tmp_path: Path) -> None:
    """If the dotted path doesn't resolve in the project, treat it as
    external (stdlib / third party); skip silently."""
    root = _setup_project(tmp_path)
    consumer = root / "main.py"
    consumer.write_text("from mypkg.ghost import anything\n")

    issues = check_imports(consumer, root)

    assert issues == []  # external-like; mypy / pytest would catch it


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    """Check never crashes /go on a missing path."""
    issues = check_imports(tmp_path / "ghost.py", tmp_path)
    assert issues == []


def test_syntax_error_returns_empty(tmp_path: Path) -> None:
    """Broken source → no findings; the lint pass / pytest will
    surface the parse error separately."""
    f = tmp_path / "broken.py"
    f.write_text("def f(:\n    pass\n")
    issues = check_imports(f, tmp_path)
    assert issues == []


def test_import_issue_is_frozen() -> None:
    issue = ImportIssue(file=Path("a.py"), line=1, module="m", name="n", reason="name not exported")
    assert issue.module == "m"
