from __future__ import annotations

from pathlib import Path

from code_scalpel.tools.shell import ShellRunner


async def ripgrep(
    pattern: str,
    root: Path,
    runner: ShellRunner,
    *,
    case_sensitive: bool = False,
    max_results: int = 50,
    context_lines: int = 0,
) -> str:
    """Search for pattern using ripgrep. Returns formatted matches or empty string."""
    cmd = ["rg", "--line-number", "--no-heading", "--color=never"]
    if not case_sensitive:
        cmd.append("--ignore-case")
    if context_lines:
        cmd += ["--context", str(context_lines)]
    cmd += ["--max-count", str(max_results), pattern, str(root)]

    result = await runner.run(cmd, timeout=10)
    return result.stdout.strip()
