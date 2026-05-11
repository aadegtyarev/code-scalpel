"""Skill ABC — pluggable per-stack contract for test / lint / format.

A Skill is a small piece of project-specific knowledge: "tests run with
pytest -x", "lint with ruff", "format with ruff format", "build with
docker compose". The agent (and TUI views) ask the registry for the
active skill rather than hardcoding shell commands; this is what lets
the same `run_tests` tool work for a Python project today and a Go one
tomorrow.

The class is deliberately tiny — a Skill is just three commands plus a
detector. Anything richer (env vars, working dir, multi-stage builds)
goes into a future subclass or a future field; today we just want the
hardcoded `pytest` call in `_tool_run_tests` to become `default_skill.
test_cmd()`.

Design notes:

* `format_cmd` returns `None` (not `[]`) when the skill has no formatter
  — empty list would be ambiguous with "run something with no args".
* `test_cmd` and `lint_cmd` always return a list; a skill that genuinely
  has no test runner shouldn't subclass `Skill` in the first place
  (compose-style skills like Docker still return *something*, even if
  it's `docker compose run app pytest`).
* `token_cost` is a rough char-count divided by 4 — same ratio used in
  session accounting. Real cost depends on how the model is prompted
  with the skill metadata, but for /skills accounting this is enough.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class Skill(ABC):
    """Abstract base for one stack's test/lint/format contract.

    Subclasses set `name` and `description` as class attributes and
    implement `detect`, `test_cmd`, `lint_cmd`. `format_cmd` defaults to
    `None` because not every stack ships an opinionated formatter.
    """

    name: str = ""
    description: str = ""

    @abstractmethod
    def detect(self, root: Path) -> bool:
        """Return True if this skill applies to the project rooted at `root`.

        Detection is a fast filesystem check — presence of a manifest
        (pyproject.toml, Dockerfile, package.json, …). It must not run
        subprocesses; the registry calls `detect` on every active() lookup.
        """

    @abstractmethod
    def test_cmd(self, args: str = "") -> list[str]:
        """Shell argv for running the project's tests.

        `args` is appended verbatim (split on whitespace) so the caller
        can request `-k pattern` or a specific test path without the
        skill needing to know.
        """

    @abstractmethod
    def lint_cmd(self) -> list[str]:
        """Shell argv for running the project's linter."""

    def format_cmd(self) -> list[str] | None:
        """Shell argv for the project's auto-formatter, or None.

        Default returns None — most stacks don't have a canonical
        formatter (Go and Python being the obvious exceptions).
        """
        return None

    def token_cost(self) -> int:
        """Approximate token cost of exposing this skill's metadata.

        Used by /skills to surface a budget number so the user can see
        what each registered skill is "costing" them in context. ~4
        chars per token matches `session.py` accounting.
        """
        return max(0, (len(self.name) + len(self.description)) // 4)
