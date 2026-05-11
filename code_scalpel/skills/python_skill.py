"""PythonSkill — pytest + ruff defaults that ship with the agent.

This is the contract the agent's `run_tests` and (eventually)
`run_lint` / `run_format` tools resolve to when the project looks like
a Python project. The detection heuristic is intentionally cheap: one
of pyproject.toml, requirements.txt, setup.py is enough — most modern
repos have at least one.

The test command pins flags chosen for LLM-friendly output:
`-x` (stop on first fail — shorter context for the model),
`--tb=short` (single-frame traceback),
`--no-header -q` (drop the rustc-style noise about platform, plugins,
collected N items — the model doesn't care).
"""

from __future__ import annotations

import shlex
from pathlib import Path

from code_scalpel.skills.base import Skill


class PythonSkill(Skill):
    name = "python"
    description = (
        "pytest + ruff for a Python project (detects pyproject.toml / requirements.txt / setup.py)."
    )

    def detect(self, root: Path) -> bool:
        for marker in ("pyproject.toml", "requirements.txt", "setup.py"):
            if (root / marker).is_file():
                return True
        return False

    def test_cmd(self, args: str = "") -> list[str]:
        # shlex.split handles "-k 'foo or bar'" correctly; plain str.split
        # would shred quoted arguments.
        extra = shlex.split(args) if args else []
        return ["pytest", "-x", "--tb=short", "--no-header", "-q", *extra]

    def lint_cmd(self) -> list[str]:
        return ["ruff", "check", "."]

    def format_cmd(self) -> list[str] | None:
        return ["ruff", "format", "."]
