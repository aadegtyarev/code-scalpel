"""Lint pass — v0.9 machine check that runs ruff/mypy on changed
files. We can't reliably depend on the host having both installed,
so the tests check the wiring (timeout, exit handling, missing
tool) rather than calling real ruff."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from code_scalpel.checks.lint_pass import LintReport, _run, lint_paths


@pytest.mark.asyncio
async def test_lint_paths_skips_missing_files(tmp_path: Path) -> None:
    """A path that doesn't exist on disk is dropped silently; the
    other paths still get reports."""
    real = tmp_path / "real.py"
    real.write_text("x = 1\n")
    fake = tmp_path / "ghost.py"

    reports = await lint_paths([real, fake], tmp_path, timeout=5)

    assert len(reports) == 1
    assert reports[0].path == real


@pytest.mark.asyncio
async def test_run_returns_empty_for_clean_exit(tmp_path: Path) -> None:
    """Linter says "all good" (exit 0) → empty string. The caller
    treats empty as nothing-to-report and skips the card."""
    out = await _run([sys.executable, "-c", "print('clean')"], cwd=tmp_path, timeout=5)
    assert out == ""


@pytest.mark.asyncio
async def test_run_returns_output_on_nonzero_exit(tmp_path: Path) -> None:
    """Non-zero exit → return combined output. The caller surfaces
    it as a chat card with `ok=False`."""
    out = await _run(
        [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(1)"],
        cwd=tmp_path,
        timeout=5,
    )
    assert "boom" in out


@pytest.mark.asyncio
async def test_run_returns_empty_when_binary_missing(tmp_path: Path) -> None:
    """`ruff` not on PATH → silent skip. /go must not crash on a
    project where the user picked a different linter."""
    out = await _run(
        [os.path.join(str(tmp_path), "no_such_bin"), "--help"],
        cwd=tmp_path,
        timeout=5,
    )
    assert out == ""


@pytest.mark.asyncio
async def test_run_returns_timeout_marker(tmp_path: Path) -> None:
    """A linter that hangs hits the timeout cap. We surface that
    explicitly rather than blocking /go forever."""
    out = await _run(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        cwd=tmp_path,
        timeout=1,
    )
    assert "timed out" in out


def test_lint_report_carries_path_and_linters() -> None:
    r = LintReport(path=Path("x.py"), findings="", ran=("ruff",))
    assert r.path.name == "x.py"
    assert r.ran == ("ruff",)
