from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.tools.git import (
    git_apply,
    git_apply_check,
    git_diff,
    git_rollback,
    git_status,
)
from code_scalpel.tools.shell import ShellResult
from tests.mocks import MockShellRunner


@pytest.mark.asyncio
async def test_git_status_command(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("M  src/main.py", 0)])
    result = await git_status(runner, tmp_path)
    assert result == "M  src/main.py"
    assert runner.calls[0] == ["git", "status", "--porcelain"]


@pytest.mark.asyncio
async def test_git_diff_command(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("--- a/f.py\n+++ b/f.py\n", 0)])
    result = await git_diff(runner, tmp_path)
    assert "--- a/f.py" in result
    assert runner.calls[0] == ["git", "diff"]


@pytest.mark.asyncio
async def test_git_diff_staged(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("", 0)])
    await git_diff(runner, tmp_path, staged=True)
    assert "--staged" in runner.calls[0]


@pytest.mark.asyncio
async def test_git_apply_check_passes_patch(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("", 0)])
    result = await git_apply_check("diff --git a/f.py b/f.py\n", runner, tmp_path)
    assert result.ok
    cmd = runner.calls[0]
    assert cmd[:3] == ["git", "apply", "--check"]
    assert "--ignore-whitespace" in cmd
    assert cmd[-1].endswith(".patch")


@pytest.mark.asyncio
async def test_git_apply_check_cleans_up_tempfile(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("", 0)])
    captured: list[str] = []

    original_run = runner.run

    async def capturing_run(
        cmd: list[str], cwd: str | None = None, timeout: int = 30
    ) -> ShellResult:
        if "apply" in cmd:
            captured.extend(cmd)
        return await original_run(cmd, cwd, timeout)

    runner.run = capturing_run  # type: ignore[method-assign]
    await git_apply_check("patch content", runner, tmp_path)
    tmp_file = next((c for c in captured if c.endswith(".patch")), None)
    assert tmp_file is not None
    assert not Path(tmp_file).exists()


@pytest.mark.asyncio
async def test_git_apply_command(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("", 0)])
    result = await git_apply("patch", runner, tmp_path)
    assert result.ok
    cmd = runner.calls[0]
    assert cmd[:2] == ["git", "apply"]
    assert "--check" not in cmd


@pytest.mark.asyncio
async def test_git_rollback_command(tmp_path: Path) -> None:
    runner = MockShellRunner([ShellResult("", 0)])
    await git_rollback(runner, tmp_path)
    assert runner.calls[0] == ["git", "restore", "."]


@pytest.mark.asyncio
async def test_git_apply_check_real(tmp_path: Path) -> None:
    """Integration: apply check on a real git repo."""
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    subprocess.run(
        ["git", "config", "user.email", "test@test.com"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Test"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )
    target = tmp_path / "hello.py"
    target.write_text("def hello():\n    pass\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "init"],
        cwd=tmp_path,
        check=True,
        capture_output=True,
    )

    patch = (
        "--- a/hello.py\n"
        "+++ b/hello.py\n"
        "@@ -1,2 +1,2 @@\n"
        " def hello():\n"
        "-    pass\n"
        '+    return "hi"\n'
    )

    from code_scalpel.tools.shell import AsyncShellRunner

    runner = AsyncShellRunner()
    result = await git_apply_check(patch, runner, tmp_path)
    assert result.ok
    assert target.read_text() == "def hello():\n    pass\n"  # --check doesn't apply
