from __future__ import annotations

from pathlib import Path

from code_scalpel.tools.git import git_apply, git_rollback
from code_scalpel.tools.shell import ShellResult, ShellRunner


async def apply_patch(patch: str, runner: ShellRunner, cwd: Path) -> ShellResult:
    """Apply patch to working tree."""
    return await git_apply(patch, runner, cwd)


async def rollback(runner: ShellRunner, cwd: Path) -> ShellResult:
    """Discard all unstaged changes."""
    return await git_rollback(runner, cwd)
