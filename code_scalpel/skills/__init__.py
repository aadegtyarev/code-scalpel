"""Skills — pluggable per-stack contracts for test / lint / format.

Public surface:

* `Skill` — ABC; subclass to define a new stack.
* `MarkdownSkill` — concrete prompt-only skill; auto-discovered from
  prompts/skills/*.md for any name not already registered.
* `SkillRegistry` — class holding registered skills.
* `register_skill(skill)` — add a skill to the global registry.
* `get_skill(name)` — fetch a registered skill by its `name` attribute.
* `active_skills(root)` — every skill whose detect() fires for `root`.
* `default_skill(root)` — first active skill, or None.

Python `Skill` subclasses in `*_skill.py` modules are auto-discovered and
registered on import, sorted by their `priority` attribute (lower = first).
Advisory prompt-only skills (e.g. git) live as prompts/skills/<name>.md and
are registered via `MarkdownSkill` without a Python class.

Adding a new stack skill = drop a `*_skill.py` here. No registration needed.
Adding a new advisory skill = drop a `<name>.md` in prompts/skills/. Ditto.
"""

from __future__ import annotations

from pathlib import Path

from code_scalpel.skills.base import MarkdownSkill, ScaffoldSpec, Skill
from code_scalpel.skills.docker_skill import DockerSkill
from code_scalpel.skills.go_skill import GoSkill
from code_scalpel.skills.js_skill import JsTsSkill
from code_scalpel.skills.postgres_skill import PostgresSkill
from code_scalpel.skills.python_cli_adapter import PythonCliAdapter
from code_scalpel.skills.python_skill import PythonSkill
from code_scalpel.skills.registry import SkillRegistry
from code_scalpel.skills.sqlite_skill import SqliteSkill

_registry = SkillRegistry()


def _auto_register_python_skills(registry: SkillRegistry) -> None:
    """Scan *_skill.py modules in this package; register all Skill subclasses.

    Sorted by `priority` (lower = registered first) so language skills
    come before component skills in default_runnable_skill lookups.
    """
    import importlib
    import pkgutil

    pkg_dir = str(Path(__file__).parent)
    seen: set[str] = set()
    pending: list[tuple[int, Skill]] = []

    for info in pkgutil.iter_modules([pkg_dir]):
        if not info.name.endswith("_skill"):
            continue
        mod = importlib.import_module(f"code_scalpel.skills.{info.name}")
        for attr in vars(mod).values():
            if not (isinstance(attr, type) and issubclass(attr, Skill)):
                continue
            if attr in (Skill, MarkdownSkill):
                continue
            skill_name: str = getattr(attr, "name", "")
            if not skill_name or skill_name in seen:
                continue
            seen.add(skill_name)
            pending.append((getattr(attr, "priority", 50), attr()))

    for _, skill in sorted(pending, key=lambda x: x[0]):
        registry.register(skill)


def _auto_register_markdown_skills(registry: SkillRegistry) -> None:
    """Register MarkdownSkill for every prompts/skills/*.md not already covered."""
    from importlib.resources import files as _files

    registered = {s.name for s in registry.all()}
    try:
        skills_res = _files("code_scalpel.prompts").joinpath("skills")
        for item in skills_res.iterdir():
            if not item.name.endswith(".md"):
                continue
            name = item.name[:-3]
            if name in registered:
                continue
            try:
                first_line = item.read_text(encoding="utf-8").splitlines()[0].strip()
            except Exception:
                first_line = f"{name.title()} instructions"
            registry.register(MarkdownSkill(name, first_line))
    except Exception:
        pass


_auto_register_python_skills(_registry)

# PythonCliAdapter is registered explicitly, NOT via _auto_register_*: its
# module is python_cli_adapter.py (not *_skill.py), so the auto-scanner
# skips it. It is registered with provides_test_runner = False (never wins
# default_runnable — PythonSkill, priority 10, stays the test runner) and
# hidden = True (excluded from the model catalog / detected-stack hint /
# /skills, since it shares PythonSkill's detect() and has no
# prompts/skills/python-cli.md behind it). It stays get_skill('python-cli')-
# discoverable for the future run-loop. This is the "discoverable without
# hijacking the test path and without polluting the model listings"
# decision (plan scenario 7 + interaction scenarios + Pass-2 finding 1).
_registry.register(PythonCliAdapter())

_auto_register_markdown_skills(_registry)


def register_skill(skill: Skill) -> None:
    """Add a Skill to the global registry. Idempotent? — no, callers
    that re-register would create duplicates; that's intentional, so
    bugs surface loudly instead of silently."""
    _registry.register(skill)


def get_skill(name: str) -> Skill | None:
    """Lookup a registered skill by `name`."""
    return _registry.get(name)


def active_skills(root: Path) -> tuple[Skill, ...]:
    """Every registered skill whose `detect(root)` returns True."""
    return _registry.active(root)


def all_skills() -> tuple[Skill, ...]:
    """Every registered skill, regardless of project detection.

    Used by the agent to build the catalog block (always visible in the
    system prompt) so the model knows which skills it can `load_skill`.
    """
    return _registry.all()


def default_skill(root: Path) -> Skill | None:
    """First active skill for `root`, or None if nothing detects."""
    return _registry.default(root)


def default_runnable_skill(root: Path) -> Skill | None:
    """First active skill that owns a test runner. Component-only skills
    (Postgres, SQLite) are skipped so they don't take over the test
    path on a polyglot repo."""
    return _registry.default_runnable(root)


def acceptance_adapter(
    root: Path, script_candidates: tuple[str, ...] | None = None
) -> Skill | None:
    """First detecting `provides_acceptance` adapter, root-bound, or None.

    The run-loop's acceptance gate (verification #4) resolves the adapter to
    run-smoke through this, so adding a language adapter needs no run-loop
    edit. `script_candidates` is the live `AgentConfig.run_smoke_script_candidates`
    the run-loop passes so a user-set candidate list reaches the resolver
    (None → the adapter's import-time default). Returns None for project types
    with no acceptance adapter."""
    return _registry.acceptance_adapter(root, script_candidates)


__all__ = [
    "DockerSkill",
    "GoSkill",
    "JsTsSkill",
    "MarkdownSkill",
    "PostgresSkill",
    "PythonCliAdapter",
    "PythonSkill",
    "ScaffoldSpec",
    "Skill",
    "SkillRegistry",
    "SqliteSkill",
    "acceptance_adapter",
    "active_skills",
    "all_skills",
    "default_runnable_skill",
    "default_skill",
    "get_skill",
    "register_skill",
]
