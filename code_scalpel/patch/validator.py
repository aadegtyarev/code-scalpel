from __future__ import annotations

from pathlib import Path

from code_scalpel.tools.git import git_apply_check
from code_scalpel.tools.shell import ShellResult, ShellRunner


async def validate_patch(patch: str, runner: ShellRunner, cwd: Path) -> ShellResult:
    """Run git apply --check. Returns ShellResult with ok=True if patch is clean."""
    return await git_apply_check(patch, runner, cwd)
