"""Run the project's own linters (ruff, mypy) on changed files.

Why bother when the model can run them via shell_exec? Because the
model on its own keeps forgetting. The whole v0.9 thesis is that
machine checks shouldn't depend on prompt discipline — if `ruff` is
on PATH and there's an obvious config in the project, /go should
run it and the model should see the findings without being asked.

Findings come back as a single string suitable for a chat card.
Empty string means clean — `run_plan` skips the card in that case.
"""

from __future__ import annotations

import asyncio
import shutil
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LintReport:
    """Combined result for one file across all configured linters."""

    path: Path
    findings: str  # multi-line string; empty when nothing flagged
    ran: tuple[str, ...]  # which linters actually ran (others skipped)


async def lint_paths(paths: list[Path], cwd: Path, *, timeout: int = 15) -> list[LintReport]:
    """Lint a batch of paths. Each path gets its own report.

    Detected linters (skip silently when missing on PATH):
      - ruff (`ruff check --no-fix --output-format=concise`)
      - mypy (`mypy --no-error-summary --pretty`)

    `timeout` caps each linter invocation; a stuck mypy on a huge
    project mustn't freeze /go.
    """
    reports: list[LintReport] = []
    have_ruff = shutil.which("ruff") is not None
    have_mypy = shutil.which("mypy") is not None
    for p in paths:
        if not p.exists():
            continue
        chunks: list[str] = []
        ran: list[str] = []
        if have_ruff:
            ran.append("ruff")
            out = await _run(
                ["ruff", "check", "--no-fix", "--output-format=concise", str(p)],
                cwd=cwd,
                timeout=timeout,
            )
            if out:
                chunks.append(f"ruff:\n{out}")
        if have_mypy:
            ran.append("mypy")
            out = await _run(
                ["mypy", "--no-error-summary", "--pretty", str(p)],
                cwd=cwd,
                timeout=timeout,
            )
            if out:
                chunks.append(f"mypy:\n{out}")
        reports.append(LintReport(path=p, findings="\n\n".join(chunks), ran=tuple(ran)))
    return reports


async def _run(argv: list[str], cwd: Path, timeout: int) -> str:
    """Run argv, return combined stdout+stderr only if exit code != 0.

    Linters report findings to stdout AND exit non-zero. A zero exit
    means "no problems"; we drop the (possibly noisy) clean-output
    summary line so the caller's empty-check works."""
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return ""
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        with _suppress_proc_kill():
            proc.kill()
        return f"(timed out after {timeout}s)"
    if proc.returncode == 0:
        return ""
    combined = (
        stdout.decode("utf-8", errors="replace") + stderr.decode("utf-8", errors="replace")
    ).strip()
    return combined


class _suppress_proc_kill:  # noqa: N801 — context-manager style
    def __enter__(self) -> None:
        return None

    def __exit__(self, *args: object) -> bool:
        return True
