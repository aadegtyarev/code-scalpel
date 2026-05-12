"""Skills — pluggable per-stack contracts for test / lint / format.

Public surface:

* `Skill` — ABC; subclass to define a new stack.
* `SkillRegistry` — class holding registered skills.
* `register_skill(skill)` — add a skill to the global registry.
* `get_skill(name)` — fetch a registered skill by its `name` attribute.
* `active_skills(root)` — every skill whose detect() fires for `root`.
* `default_skill(root)` — first active skill, or None.

Built-ins (PythonSkill, DockerSkill) are registered on import. The
global registry lives in this module; tests can clear it via the
private `_registry._reset()` hook.
"""

from __future__ import annotations

from pathlib import Path

from code_scalpel.skills.base import Skill
from code_scalpel.skills.docker_skill import DockerSkill
from code_scalpel.skills.go_skill import GoSkill
from code_scalpel.skills.js_skill import JsTsSkill
from code_scalpel.skills.postgres_skill import PostgresSkill
from code_scalpel.skills.python_skill import PythonSkill
from code_scalpel.skills.registry import SkillRegistry
from code_scalpel.skills.sqlite_skill import SqliteSkill

# Registration order is the priority order for `default_runnable_skill`.
# Language skills come first so a polyglot repo (Python + Postgres,
# Go + Docker) picks the language's test runner. Container skill next
# (Docker — has its own test command via `docker compose`). Component
# skills (Postgres, SQLite) ship `provides_test_runner = False` so they
# don't compete for the test path regardless of order.
_registry = SkillRegistry()
_registry.register(PythonSkill())
_registry.register(JsTsSkill())
_registry.register(GoSkill())
_registry.register(DockerSkill())
_registry.register(PostgresSkill())
_registry.register(SqliteSkill())


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


def default_skill(root: Path) -> Skill | None:
    """First active skill for `root`, or None if nothing detects."""
    return _registry.default(root)


def default_runnable_skill(root: Path) -> Skill | None:
    """First active skill that owns a test runner. Component-only skills
    (Postgres, SQLite) are skipped so they don't take over the test
    path on a polyglot repo."""
    return _registry.default_runnable(root)


__all__ = [
    "DockerSkill",
    "GoSkill",
    "JsTsSkill",
    "PostgresSkill",
    "PythonSkill",
    "Skill",
    "SkillRegistry",
    "SqliteSkill",
    "active_skills",
    "default_runnable_skill",
    "default_skill",
    "get_skill",
    "register_skill",
]
