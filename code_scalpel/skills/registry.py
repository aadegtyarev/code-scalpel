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
        """Model-facing catalog: every listed skill (hidden ones excluded).

        `hidden` skills stay registered — `get(name)`, `default` and
        `default_runnable` still see them — but never appear in the
        catalog the model is shown, so a discovery-only adapter does not
        advertise a row with no prompts/skills guidance behind it.
        """
        return tuple(s for s in self._skills if not s.hidden)

    def active(self, root: Path) -> tuple[Skill, ...]:
        """Listed skills that claim this root, in registration order.

        Mirrors `all()` on the `hidden` exclusion: this backs the
        detected-stack hint and the `/skills` panel, both model/user
        facing. `default`/`default_runnable` keep their own unfiltered
        scan over `_skills` so detection selection is unaffected.
        """
        return tuple(s for s in self._skills if not s.hidden and s.detect(root))

    def default(self, root: Path) -> Skill | None:
        """Return the first active skill, or None if nothing detects."""
        for s in self._skills:
            if s.detect(root):
                return s
        return None

    def default_runnable(self, root: Path) -> Skill | None:
        """First active skill that owns a test runner. Component-only
        skills (Postgres, SQLite — `provides_test_runner = False`)
        detect the stack but don't take over the test path; this lets a
        Python+Postgres project keep running pytest while still
        surfacing Postgres in `/skills`.
        """
        for s in self._skills:
            if s.detect(root) and s.provides_test_runner:
                return s
        return None

    def acceptance_adapter(
        self, root: Path, script_candidates: tuple[str, ...] | None = None
    ) -> Skill | None:
        """First detecting `provides_acceptance` skill, root-bound, or None.

        A selection method like `get`/`default`/`default_runnable`: it scans
        `_skills` **unfiltered**, so a `hidden` adapter (PythonCliAdapter) is
        eligible. Detection runs on the rootless registry singleton; the
        returned instance is `.bind(root, script_candidates)`, so
        `acceptance_spec`/`run_smoke` are never called on the rootless one
        (which raises). `script_candidates` is the live config value the
        run-loop threads through so a user-set candidate list reaches the
        resolver (None → the adapter's import-time default). Returns None when
        no acceptance adapter detects the root.
        """
        for s in self._skills:
            if s.provides_acceptance and s.detect(root):
                return s.bind(root, script_candidates)
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
