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

    def model_instructions(self) -> str:
        return """\
Python project rules:
- ALWAYS work inside a virtualenv. If `.venv/` is missing, your FIRST
  shell_exec for this project is `python3 -m venv .venv` (use `python3`,
  not `python` — on Debian/Ubuntu the bare `python` symlink often
  doesn't exist). Subsequent
  commands MUST use `.venv/bin/python` / `.venv/bin/pip` / `.venv/bin/pytest`
  explicitly (do not rely on shell activation — each shell_exec is a fresh
  subprocess and `source .venv/bin/activate` does not persist).
- Right after creating `.venv/`, make sure `.gitignore` excludes it. Add
  these lines (use `write_file` with `insert_after_line=0` if .gitignore
  is missing, or append): `.venv/`, `__pycache__/`, `*.pyc`, `.pytest_cache/`,
  `dist/`, `build/`, `*.egg-info/`.
- Install deps: `.venv/bin/pip install -r requirements.txt` (or `-e .` for
  editable installs of the project itself).
- Tests: `.venv/bin/pytest -x --tb=short --no-header -q` (stop on first fail).
- Lint: `.venv/bin/ruff check .` — auto-fix: `.venv/bin/ruff check --fix .`
- Format: `.venv/bin/ruff format .`
- Test fails → read the traceback, fix the code, rerun tests.
- Lint error → fix it, don't suppress with `# noqa` unless unavoidable.
- Git: don't commit `.venv/` or test/build artifacts (covered by the
  .gitignore above). For a new project: `git init` then create .gitignore
  BEFORE the first `git add`.\
"""
