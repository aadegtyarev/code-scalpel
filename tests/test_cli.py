"""CLI surface tests — keep `code-scalpel --version` honest.

The version itself lives in pyproject.toml; `code_scalpel.__version__`
reads it through importlib.metadata. The CLI flag just prints it and
exits — but it has to actually be wired, hence this test.
"""

from __future__ import annotations

from typer.testing import CliRunner

from code_scalpel import __version__
from code_scalpel.cli import app


def test_version_flag_prints_and_exits() -> None:
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert __version__ in result.stdout
    assert "code-scalpel" in result.stdout


def test_version_string_is_resolved_not_placeholder() -> None:
    """A `0.0.0+local` fallback means the package wasn't installed; in CI /
    dev environments we install with `pip install -e .` so the real
    pyproject version should resolve."""
    assert __version__ != "0.0.0+local", (
        "package metadata didn't resolve — did you forget `pip install -e .`?"
    )
