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
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path


@dataclass(frozen=True)
class ScaffoldSpec:
    """Inputs a `Skill.scaffold` needs to emit a runnable skeleton.

    `root` is the project directory the skeleton is written into; `pkg`
    is the importable package name the deliverable will be run as
    (`python -m <pkg>` for python-cli). Kept deliberately small — richer
    adapters add their own fields in a subclass-specific spec if needed.
    """

    root: Path
    pkg: str


class Skill(ABC):
    """Abstract base for one stack's test/lint/format contract.

    Subclasses set `name` and `description` as class attributes and
    implement `detect`, `test_cmd`, `lint_cmd`. `format_cmd` defaults to
    `None` because not every stack ships an opinionated formatter.

    `provides_test_runner` distinguishes **language skills** (Python,
    JS/TS, Go — own primary test command) from **component skills**
    (Postgres, SQLite — detect that the stack uses the component, but
    have no standalone test runner). The registry's
    `default_runnable_skill` skips non-runnable ones so a
    Python-with-Postgres project still runs `pytest`, not an empty
    Postgres test_cmd.
    """

    name: str = ""
    description: str = ""
    provides_test_runner: bool = True
    priority: int = 50  # lower = registered first; controls default_runnable_skill order

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

    def lint_file_cmd(self, path: Path) -> list[str] | None:
        """Shell argv for linting a single file, or None if not supported.

        Used by the agent to inject quick lint feedback directly into a
        write_file tool result so the model sees errors in the same turn.
        Should be fast (< 5s) — avoid whole-project passes here.

        Default returns None (no per-file linting). Override in language
        skills that have a file-level linter (ruff, eslint).
        """
        return None

    def model_instructions(self) -> str:
        """Model-facing block injected into the system prompt when the skill loads.

        Loaded from `code_scalpel/prompts/skills/<name>.md` by convention.
        Returns empty string when no file exists for this skill.
        Subclasses can override if they need dynamic content.
        """
        try:
            return (
                files("code_scalpel.prompts")
                .joinpath(f"skills/{self.name}.md")
                .read_text()
                .rstrip("\n")
            )
        except (FileNotFoundError, TypeError):
            return ""

    def token_cost(self) -> int:
        """Approximate token cost of exposing this skill's metadata.

        Used by /skills to surface a budget number so the user can see
        what each registered skill is "costing" them in context. ~4
        chars per token matches `session.py` accounting.
        """
        return max(0, (len(self.name) + len(self.description)) // 4)

    # ── ProjectAdapter superset ──────────────────────────────────────────
    # These four make a Skill a full "project adapter" — not just how to
    # test, but how to build/run/scaffold the actual deliverable. They are
    # NON-abstract with safe defaults so every existing Skill stays
    # concrete and instantiable; an adapter (e.g. PythonCliAdapter)
    # overrides them. They are intentionally inert here: no run-loop
    # consumes them yet (that is a later feature) — this just makes the
    # contract exist.

    def build_install(self) -> list[str]:
        """Shell argv to make the deliverable runnable, or `[]` if none.

        Default `[]` — a plain Skill knows how to test, but not how to
        install/build the product. Adapters override (e.g. python-cli
        returns `pip install -e .`).
        """
        return []

    def run_smoke(self, args: str = "") -> list[str]:
        """Shell argv to run the actual deliverable as a user would.

        Default `[]` — a plain Skill has no run-smoke. `args` is appended
        (whitespace-split) like `test_cmd`. Adapters override (e.g.
        python-cli returns `python -m <pkg> <args>`).
        """
        return []

    def scaffold(self, spec: ScaffoldSpec) -> list[Path]:
        """Write a deterministic runnable skeleton; return files created.

        Default no-op: returns `[]` (this skill does not own a project
        skeleton). Adapters override to emit the code-owned entrypoint
        plumbing instead of leaving it to the model's whim.
        """
        return []

    def acceptance_spec(self, task: object) -> tuple[str, str] | None:
        """`(command, expected_observable)` for "actually works", or None.

        Default `None` — a plain Skill declares no acceptance contract.
        Adapters override (python-cli returns the built-in default-floor).
        """
        return None


class MarkdownSkill(Skill):
    """Prompt-only skill backed by prompts/skills/<name>.md.

    Never auto-detected — must be loaded explicitly via load_skill().
    Use for advisory skills (git workflow, etc.) where the model already
    knows the basics but needs specific rules for edge cases.
    """

    provides_test_runner: bool = False

    def __init__(self, skill_name: str, skill_description: str = "") -> None:
        self.name = skill_name
        self.description = skill_description or f"{skill_name.title()} instructions"

    def detect(self, root: Path) -> bool:
        return False

    def test_cmd(self, args: str = "") -> list[str]:
        return []

    def lint_cmd(self) -> list[str]:
        return []
