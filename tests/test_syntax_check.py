from __future__ import annotations

from pathlib import Path

from code_scalpel.checks import check_syntax
from code_scalpel.checks.syntax_check import SyntaxIssue


def test_valid_python_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "ok.py"
    p.write_text("def add(x):\n    return x + 1\n")
    assert check_syntax(p) is None


def test_stray_quote_is_caught(tmp_path: Path) -> None:
    """Реальный кейс из живого прогона: хвостовой `")` ломает строку."""
    p = tmp_path / "cli.py"
    p.write_text('print("usage: cli.py add \\"note\\"")")\n')
    issue = check_syntax(p)
    assert isinstance(issue, SyntaxIssue)
    assert issue.line == 1
    assert issue.message  # непустое сообщение


def test_unclosed_bracket_is_caught(tmp_path: Path) -> None:
    p = tmp_path / "broken.py"
    p.write_text("def f(:\n    pass\n")
    issue = check_syntax(p)
    assert issue is not None
    assert issue.file == p


def test_non_python_returns_none(tmp_path: Path) -> None:
    p = tmp_path / "data.json"
    p.write_text("{not valid python but also not .py}")
    assert check_syntax(p) is None


def test_missing_file_returns_none(tmp_path: Path) -> None:
    assert check_syntax(tmp_path / "nope.py") is None
