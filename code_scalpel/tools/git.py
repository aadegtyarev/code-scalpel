from __future__ import annotations

import tempfile
from pathlib import Path

from code_scalpel.tools.shell import ShellResult, ShellRunner


async def git_status(runner: ShellRunner, cwd: Path) -> str:
    result = await runner.run(["git", "status", "--porcelain"], cwd=str(cwd))
    return result.stdout.strip()


async def git_diff(runner: ShellRunner, cwd: Path, *, staged: bool = False) -> str:
    cmd = ["git", "diff"]
    if staged:
        cmd.append("--staged")
    result = await runner.run(cmd, cwd=str(cwd))
    return result.stdout


async def git_apply_check(patch: str, runner: ShellRunner, cwd: Path) -> ShellResult:
    """Dry-run: verify patch applies cleanly without touching working tree."""
    with tempfile.NamedTemporaryFile(suffix=".patch", mode="w", delete=False) as f:
        f.write(patch)
        tmp = f.name
    try:
        return await runner.run(
            ["git", "apply", "--check", "--ignore-whitespace", tmp], cwd=str(cwd)
        )
    finally:
        Path(tmp).unlink(missing_ok=True)


async def git_apply(patch: str, runner: ShellRunner, cwd: Path) -> ShellResult:
    """Apply patch to working tree."""
    with tempfile.NamedTemporaryFile(suffix=".patch", mode="w", delete=False) as f:
        f.write(patch)
        tmp = f.name
    try:
        return await runner.run(["git", "apply", "--ignore-whitespace", tmp], cwd=str(cwd))
    finally:
        Path(tmp).unlink(missing_ok=True)


async def git_rollback(runner: ShellRunner, cwd: Path) -> ShellResult:
    """Discard all unstaged changes in working tree."""
    return await runner.run(["git", "restore", "."], cwd=str(cwd))
