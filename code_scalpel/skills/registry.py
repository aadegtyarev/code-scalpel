"""SkillRegistry — module-global list of registered skills.

The registry is a flat list, not a dict — order of registration is
meaningful (first-registered Python wins over a later user override
unless they explicitly replace it). `active(root)` returns every skill
whose `detect()` fires for the given root; `default(root)` returns the
first match or None.

Built-in skills (PythonSkill, DockerSkill) are registered in
`__init__.py` on import, so any code that does `from code_scalpel.skills
import get_skill` gets the standard set for free. Users add their own
with `register_skill(MySkill())` before instantiating the agent.

There's only one global registry instance. A dependency-injected design
would be cleaner but the registry is, by nature, process-wide config —
the agent and the TUI must agree on which skills exist, and threading
it through every constructor would be busywork. If tests need
isolation, they can call `SkillRegistry._reset()` (intentionally
underscore-prefixed: this is for the test suite, not production code).
"""

from __future__ import annotations

from pathlib import Path

from code_scalpel.skills.base import Skill


class SkillRegistry:
    """Holds the list of registered Skill instances.

    Use `register(skill)` to add, `active(root)` to filter by
    project-shape detection, `default(root)` for the first match.
    """

    def __init__(self) -> None:
        self._skills: list[Skill] = []

    def register(self, skill: Skill) -> None:
        self._skills.append(skill)

    def all(self) -> tuple[Skill, ...]:
        return tuple(self._skills)

    def active(self, root: Path) -> tuple[Skill, ...]:
        """Return every skill that claims this root, in registration order."""
        return tuple(s for s in self._skills if s.detect(root))

    def default(self, root: Path) -> Skill | None:
        """Return the first active skill, or None if nothing detects."""
        for s in self._skills:
            if s.detect(root):
                return s
        return None

    def get(self, name: str) -> Skill | None:
        """Lookup by class-attribute `name`. Returns None if not registered."""
        for s in self._skills:
            if s.name == name:
                return s
        return None

    def _reset(self) -> None:
        """Test-only: clear the registry so each test starts blank.

        Not part of the public API — production code should never need
        to nuke the registry mid-run.
        """
        self._skills.clear()
