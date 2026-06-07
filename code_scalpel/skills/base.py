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

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib.resources import files
from pathlib import Path
from typing import Literal


class AcceptanceArgError(ValueError):
    """A derived/declared acceptance `args` string could not be tokenized.

    Raised by `run_smoke` when `shlex.split(args)` fails (unbalanced quotes
    in a model-supplied args string). Distinct from the `ValueError`
    `resolve_pkg` raises for an unresolvable package: a malformed-args error
    is a property of the SPEC (fall back to floor/observational), not of the
    package (which is healthy) — so the run-loop must not mislabel it
    `pkg-unresolvable` and demote a sound project (review finding 5). Subclasses
    ValueError so existing `except ValueError` sites stay backward-compatible,
    but the run-loop catches this FIRST to route it differently.
    """


@dataclass(frozen=True)
class AcceptanceSpec:
    """The "does the deliverable actually work?" check the run-loop runs.

    `command` is the adapter-built argv-string (code-owned assembly — the
    verb is always the adapter's, never a model-emitted shell line);
    `expected` is the observable substring a `passed` verdict requires
    (`""` ⇒ exit-0-only); `applicable` gates ENFORCEMENT — `True` lets
    verification #4 demote `done → failed` on failure, `False` keeps it
    observational (the library no-regression lock; the default-floor and a
    derivation that found no runnable CLI both set `False`). `source` is the
    provenance, surfaced on the card and recorded for feature 3's self-fix.

    Replaces feature 2's `(command, expected)` 2-tuple: applicability could
    not ride a 2-tuple without the run-loop inferring it, which would
    re-inject language knowledge into the loop (KD4).
    """

    command: str
    expected: str
    applicable: bool
    source: Literal["declared", "derived", "floor"]


# Write-back encoding for a narrow-pass-DERIVED acceptance result. A derived
# result is persisted into `Task.acceptance` (the JSON-canonical, round-trips
# via `task_from_json`) as a SINGLE marker line so the next run reads it back
# instead of re-deriving — and so "derived: not applicable" is distinguishable
# from "not yet derived" (empty acceptance). The marker is JSON after a stable
# prefix so it round-trips through the tuple-of-strings field losslessly and a
# human-declared acceptance bullet (free prose) never collides with it.
_DERIVED_MARKER_PREFIX = "derived-acceptance:"


def encode_derived_acceptance(*, applicable: bool, args: str, expected: str) -> str:
    """Build the single `Task.acceptance` marker line for a derived spec.

    Carries `applicable` so a derived not-applicable result (a library) is
    persisted and never re-derived, and `args` so the adapter rebuilds the
    code-owned argv via `run_smoke(args)` on every later run.
    """
    payload = {"applicable": applicable, "args": args, "expected": expected}
    return _DERIVED_MARKER_PREFIX + json.dumps(payload, ensure_ascii=False, sort_keys=True)


def decode_derived_acceptance(line: str) -> dict[str, object] | None:
    """Parse a derived marker line into `{applicable, args, expected}`, or None.

    None for any line that is not a derived marker (a human-declared
    acceptance bullet, or malformed JSON) — the caller then treats the
    acceptance as task-declared (B) or absent.
    """
    if not line.startswith(_DERIVED_MARKER_PREFIX):
        return None
    try:
        data = json.loads(line[len(_DERIVED_MARKER_PREFIX) :])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "applicable" not in data:
        return None
    return data


def is_marker_prefixed(line: str) -> bool:
    """True for any line carrying the derived-marker prefix, decodable or not.

    Lets a caller distinguish a *malformed* derived marker (prefix present,
    JSON unparseable → `decode_derived_acceptance` returns None) from a real
    human-declared prose bullet (no prefix). A malformed marker must be
    treated as ABSENT (re-derive) — never as a declared spec or enforceable
    args (review finding 4).
    """
    return line.startswith(_DERIVED_MARKER_PREFIX)


def acceptance_needs_derivation(bullets: tuple[str, ...]) -> bool:
    """True when the task should run the derivation pre-pass.

    Derivation is SKIPPED only when a DECODABLE derived marker (C) is already
    present — that run is done and deterministic. Everything else needs
    derivation: an empty tuple; a human-declared PROSE bullet (B), which is
    fed to the model as an intent HINT, never run as argv (review finding 2);
    and a MALFORMED derived marker, treated as absent so a corrupt write-back
    self-heals instead of wedging the task (review finding 4).
    """
    return all(decode_derived_acceptance(line) is None for line in bullets)


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
    # Symmetric with `provides_test_runner`: marks an adapter that owns an
    # acceptance / run-smoke contract (its `acceptance_spec` returns a real
    # command). The run-loop's verification #4 selects the first detecting
    # skill with this flag via `SkillRegistry.acceptance_adapter`. Default
    # False — a plain Skill declares no acceptance contract.
    provides_acceptance: bool = False
    priority: int = 50  # lower = registered first; controls default_runnable_skill order
    # `hidden` keeps a skill in the registry (so `get_skill(name)` and the
    # detection paths `default`/`default_runnable` still see it) while
    # excluding it from the model-facing listings — the catalog `all()`,
    # the active-skills listing `active()`, the detected-stack hint and the
    # `/skills` panel that build on them. Used by adapters like
    # PythonCliAdapter that share a detect() with a real skill (PythonSkill)
    # and would otherwise advertise a duplicate row with no prompts/skills
    # guidance file behind it. Default False — every ordinary skill lists.
    hidden: bool = False

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

        `args` is appended after being split with shlex (quoted groups
        preserved), so the caller can request `-k 'foo or bar'` or a
        specific test path without the skill needing to know.
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

    def bind(self, root: Path, script_candidates: tuple[str, ...] | None = None) -> Skill:
        """Return an instance of this skill bound to `root`, for run-smoke.

        Default is the *identity bind* — a stateless skill (or a component
        skill / rootless discovery singleton) needs no root context, so it
        returns `self` unchanged. Adapters that resolve a root-dependent
        deliverable (python-cli resolves `<pkg>` from the tree) override
        this to return a root-bound instance. Polymorphic so the registry
        can root-bind any adapter without knowing its constructor shape.

        `script_candidates`, when provided, is the live config value an
        adapter uses for the lowest run-smoke resolution rung; the default
        bind ignores it (a stateless skill has no run-smoke resolution).
        """
        return self

    def build_install(self) -> list[str]:
        """Shell argv to make the deliverable runnable, or `[]` if none.

        Default `[]` — a plain Skill knows how to test, but not how to
        install/build the product. Adapters override (e.g. python-cli
        returns `pip install -e .`).
        """
        return []

    def run_smoke(self, args: str = "") -> list[str]:
        """Shell argv to run the actual deliverable as a user would.

        Default `[]` — a plain Skill has no run-smoke. `args` is split
        with shlex, like `test_cmd`, then appended. Adapters override
        (e.g. python-cli returns `python -m <pkg> <args>`).
        """
        return []

    def scaffold(self, spec: ScaffoldSpec) -> list[Path]:
        """Write a deterministic runnable skeleton; return files created.

        Default no-op: returns `[]` (this skill does not own a project
        skeleton). Adapters override to emit the code-owned entrypoint
        plumbing instead of leaving it to the model's whim.
        """
        return []

    def acceptance_spec(self, task: object) -> AcceptanceSpec | None:
        """The "actually works" check for this task, or None.

        Default `None` — a plain Skill declares no acceptance contract.
        Adapters override (python-cli returns the precedence B→C→A spec,
        the default-floor being `applicable=False`).
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
