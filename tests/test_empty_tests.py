"""AST detector for empty/trivial tests — v0.9 machine check."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.checks import EmptyTest, detect_empty_tests


def test_detects_pass_body(tmp_path: Path) -> None:
    f = tmp_path / "test_x.py"
    f.write_text("def test_smoke():\n    pass\n")
    bad = detect_empty_tests(f)
    assert len(bad) == 1
    assert bad[0].name == "test_smoke"


def test_detects_assert_true(tmp_path: Path) -> None:
    f = tmp_path / "test_x.py"
    f.write_text("def test_smoke():\n    assert True\n")
    bad = detect_empty_tests(f)
    assert len(bad) == 1
    assert "literal" in bad[0].reason


def test_detects_literal_equality(tmp_path: Path) -> None:
    f = tmp_path / "test_x.py"
    f.write_text("def test_smoke():\n    assert 1 == 1\n")
    bad = detect_empty_tests(f)
    assert len(bad) == 1


def test_detects_only_ellipsis(tmp_path: Path) -> None:
    f = tmp_path / "test_x.py"
    f.write_text("def test_todo():\n    ...\n")
    bad = detect_empty_tests(f)
    assert len(bad) == 1
    assert "pass/" in bad[0].reason


def test_detects_docstring_only(tmp_path: Path) -> None:
    f = tmp_path / "test_x.py"
    f.write_text('def test_todo():\n    """TODO"""\n')
    bad = detect_empty_tests(f)
    assert len(bad) == 1
    assert "empty body" in bad[0].reason


def test_accepts_real_assert(tmp_path: Path) -> None:
    """A function call + assert on its result is meaningful enough at
    the structural level. (Behavioural weakness like
    `assert x is not None` is the LLM judge's territory.)"""
    f = tmp_path / "test_x.py"
    f.write_text(
        "from mod import greet\n\n"
        "def test_smoke():\n"
        "    result = greet()\n"
        "    assert result == 'hello'\n"
    )
    bad = detect_empty_tests(f)
    assert bad == []


def test_accepts_isinstance_check(tmp_path: Path) -> None:
    """`assert isinstance(x, T)` involves a Call expression — passes
    the structural check, even though it's behaviourally weak."""
    f = tmp_path / "test_x.py"
    f.write_text(
        "from mod import greet\n\ndef test_smoke():\n    assert isinstance(greet(), str)\n"
    )
    bad = detect_empty_tests(f)
    assert bad == []


def test_ignores_non_test_functions(tmp_path: Path) -> None:
    """Functions without `test_` prefix aren't tests."""
    f = tmp_path / "test_x.py"
    f.write_text(
        "def helper():\n    pass\n\ndef test_real():\n    from mod import x\n    assert x() == 1\n"
    )
    bad = detect_empty_tests(f)
    assert bad == []


def test_async_test(tmp_path: Path) -> None:
    """Async tests count the same way."""
    f = tmp_path / "test_x.py"
    f.write_text("async def test_smoke():\n    assert True\n")
    bad = detect_empty_tests(f)
    assert len(bad) == 1


def test_missing_file_returns_empty(tmp_path: Path) -> None:
    bad = detect_empty_tests(tmp_path / "nope.py")
    assert bad == []


def test_syntax_error_returns_empty(tmp_path: Path) -> None:
    """Detector never crashes /go — bad Python returns []."""
    f = tmp_path / "broken.py"
    f.write_text("def test_x(:\n    pass\n")
    bad = detect_empty_tests(f)
    assert bad == []


def test_empty_test_dataclass_is_hashable() -> None:
    """Frozen so we can use it in sets if /go ever wants dedup."""
    from dataclasses import FrozenInstanceError

    a = EmptyTest(name="x", reason="r")
    {a}  # noqa — just an existence check
    with pytest.raises(FrozenInstanceError):
        a.reason = "y"  # type: ignore[misc]
