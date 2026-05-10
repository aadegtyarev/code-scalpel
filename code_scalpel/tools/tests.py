from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from code_scalpel.tools.shell import ShellResult, ShellRunner

_SUMMARY_RE = re.compile(r"(\d+) passed(?:,\s*(\d+) failed)?.*?in ([\d.]+)s")
_FAILED_ONLY_RE = re.compile(r"(\d+) failed")


@dataclass(frozen=True)
class RunResult:
    passed: int
    failed: int
    duration: float
    output: str
    ok: bool


async def run_tests(
    cmd: list[str],
    runner: ShellRunner,
    cwd: Path,
    timeout: int = 60,
) -> RunResult:
    result: ShellResult = await runner.run(cmd, cwd=str(cwd), timeout=timeout)
    return _parse(result)


def _parse(result: ShellResult) -> RunResult:
    out = result.stdout

    m = _SUMMARY_RE.search(out)
    if m:
        passed = int(m.group(1))
        failed = int(m.group(2) or 0)
        duration = float(m.group(3))
        return RunResult(
            passed=passed,
            failed=failed,
            duration=duration,
            output=out,
            ok=result.ok and failed == 0,
        )

    m2 = _FAILED_ONLY_RE.search(out)
    failed = int(m2.group(1)) if m2 else 0
    return RunResult(passed=0, failed=failed, duration=0.0, output=out, ok=result.ok)
