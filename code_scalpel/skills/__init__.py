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
from code_scalpel.skills.python_skill import PythonSkill
from code_scalpel.skills.registry import SkillRegistry

_registry = SkillRegistry()
_registry.register(PythonSkill())
_registry.register(DockerSkill())


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


__all__ = [
    "DockerSkill",
    "PythonSkill",
    "Skill",
    "SkillRegistry",
    "active_skills",
    "default_skill",
    "get_skill",
    "register_skill",
]
