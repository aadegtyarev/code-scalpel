from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.tools.search import ripgrep
from code_scalpel.tools.shell import ShellResult
from tests.mocks import MockShellRunner


@pytest.mark.asyncio
async def test_ripgrep_passes_pattern_and_root(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("src/main.py:10:def hello():", 0)])
    result = await ripgrep("hello", tmp_path, runner)
    assert result == "src/main.py:10:def hello():"
    cmd = runner.calls[0]
    assert cmd[0] == "rg"
    assert "hello" in cmd
    assert str(tmp_path) in cmd


@pytest.mark.asyncio
async def test_ripgrep_case_insensitive_by_default(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("", 0)])
    await ripgrep("Hello", tmp_path, runner)
    assert "--ignore-case" in runner.calls[0]


@pytest.mark.asyncio
async def test_ripgrep_case_sensitive(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("", 0)])
    await ripgrep("Hello", tmp_path, runner, case_sensitive=True)
    assert "--ignore-case" not in runner.calls[0]


@pytest.mark.asyncio
async def test_ripgrep_no_results(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("", 1)])
    result = await ripgrep("nonexistent", tmp_path, runner)
    assert result == ""


@pytest.mark.asyncio
async def test_ripgrep_real(tmp_path: Path) -> None:
    import shutil

    if not shutil.which("rg"):
        pytest.skip("ripgrep not installed")
    (tmp_path / "hello.py").write_text("def hello():\n    pass\n")
    from code_scalpel.tools.shell import AsyncShellRunner

    runner = AsyncShellRunner(whitelist=frozenset({"rg"}))
    result = await ripgrep("def hello", tmp_path, runner)
    assert "hello" in result
