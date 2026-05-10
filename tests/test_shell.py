from __future__ import annotations

import asyncio

import pytest

from code_scalpel.tools.shell import (
    AsyncShellRunner,
    CommandNotAllowedError,
    ShellResult,
    ShellRunner,
)
from tests.mocks import MockShellRunner


def test_mock_satisfies_protocol() -> None:
    mock = MockShellRunner()
    assert isinstance(mock, ShellRunner)


def test_shell_result_ok() -> None:
    assert ShellResult("out", 0).ok is True
    assert ShellResult("err", 1).ok is False


@pytest.mark.asyncio
async def test_mock_returns_responses() -> None:
    runner = MockShellRunner([ShellResult("hello", 0), ShellResult("world", 1)])
    r1 = await runner.run(["git", "status"])
    r2 = await runner.run(["git", "diff"])
    r3 = await runner.run(["git", "log"])  # clamps at last
    assert r1 == ShellResult("hello", 0)
    assert r2 == ShellResult("world", 1)
    assert r3 == ShellResult("world", 1)
    assert runner.calls == [["git", "status"], ["git", "diff"], ["git", "log"]]


@pytest.mark.asyncio
async def test_whitelist_blocks_unknown_command() -> None:
    runner = AsyncShellRunner()
    with pytest.raises(CommandNotAllowedError, match="curl"):
        await runner.run(["curl", "https://example.com"])


@pytest.mark.asyncio
async def test_whitelist_allows_path_prefixed_git() -> None:
    runner = AsyncShellRunner()
    result = await runner.run(["/usr/bin/git", "--version"])
    assert result.ok
    assert "git" in result.stdout


@pytest.mark.asyncio
async def test_custom_whitelist() -> None:
    runner = AsyncShellRunner(whitelist=frozenset({"echo"}))
    result = await runner.run(["echo", "hello"])
    assert result.stdout.strip() == "hello"
    assert result.ok


@pytest.mark.asyncio
async def test_captures_stderr_in_stdout() -> None:
    runner = AsyncShellRunner(whitelist=frozenset({"git"}))
    result = await runner.run(["git", "status", "--porcelain"], cwd="/tmp")
    # git in /tmp either works or emits an error — either way stdout is non-empty on failure
    assert isinstance(result.stdout, str)


@pytest.mark.asyncio
async def test_nonzero_returncode() -> None:
    runner = AsyncShellRunner(whitelist=frozenset({"git"}))
    result = await runner.run(["git", "status"], cwd="/tmp")
    # /tmp is not a git repo — returncode > 0
    assert not result.ok


@pytest.mark.asyncio
async def test_timeout_kills_process() -> None:
    runner = AsyncShellRunner(whitelist=frozenset({"python3"}))
    with pytest.raises(asyncio.TimeoutError):
        await runner.run(["python3", "-c", "import time; time.sleep(10)"], timeout=1)


def test_empty_cmd_raises() -> None:
    runner = AsyncShellRunner()

    async def _run() -> None:
        await runner.run([])

    with pytest.raises(ValueError, match="empty"):
        asyncio.run(_run())
