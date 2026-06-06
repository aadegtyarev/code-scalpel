"""PythonCliAdapter — the first ProjectAdapter (superset of Skill).

A python-cli project's single source of truth for how to build, test,
run, scaffold, and accept the *actual deliverable* — a CLI invoked as
`python -m <pkg>`. It extends the Skill contract with the four
ProjectAdapter methods (`build_install`, `run_smoke`, `scaffold`,
`acceptance_spec`); `test()` reuses PythonSkill's exact pytest command so
the test path never drifts from the existing skill.

Why a separate registration (not auto-discovered like *_skill.py):
`PythonCliAdapter.detect` fires on the same manifests as PythonSkill, so
if it auto-registered as a runnable test skill it could hijack
`default_runnable` for ordinary Python projects. It is registered
explicitly in `__init__.py` with `provides_test_runner = False`, so it is
discoverable via `get_skill`/`all_skills` but never selected by
`default_runnable` — the existing PythonSkill stays the test runner.

Determinism is the point: the `__main__.py` entrypoint and the hatchling
src-layout config are code-owned here, not emitted by the model's whim
(the documented `notes_cli` coin-flip).
"""

from __future__ import annotations

import re
from pathlib import Path

from code_scalpel.skills.base import ScaffoldSpec, Skill
from code_scalpel.skills.python_pkg import resolve_pkg
from code_scalpel.skills.python_skill import PythonSkill

# PEP 8 / importlib package-name shape: identifier-ish, no leading digit.
_PKG_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# Built-in default-floor acceptance for a python-cli deliverable: it must
# be `-m`-runnable and `--help` must exit cleanly. Task-declared and
# narrow-pass-derived specs are a later feature; this is the minimum.
_DEFAULT_FLOOR_HELP_ARGS = "--help"


class PythonCliAdapter(Skill):
    name = "python-cli"
    description = "python-cli project adapter: pip install -e ., pytest, python -m <pkg> run-smoke."
    # Detection-only for the registry's test-path selection: PythonSkill
    # owns the test runner for Python projects. See module docstring.
    provides_test_runner = False
    priority = 15

    def __init__(self, root: Path | None = None) -> None:
        # `root` lets an adapter instance resolve <pkg> deterministically
        # for run_smoke. The registry constructs it with no root (a
        # detection/discovery singleton); a caller that wants run_smoke
        # constructs PythonCliAdapter(root=project_root).
        self._root = root

    def detect(self, root: Path) -> bool:
        # Same heuristic as PythonSkill — a python-cli project IS a Python
        # project; the adapter does not narrow detection further here.
        return PythonSkill().detect(root)

    def test_cmd(self, args: str = "") -> list[str]:
        # Reuse PythonSkill verbatim so the test command never drifts.
        return PythonSkill().test_cmd(args)

    def test(self, args: str = "") -> list[str]:
        """Alias for `test_cmd` — the ProjectAdapter-facing name."""
        return self.test_cmd(args)

    def lint_cmd(self) -> list[str]:
        return PythonSkill().lint_cmd()

    def build_install(self) -> list[str]:
        return ["pip", "install", "-e", "."]

    def run_smoke(self, args: str = "") -> list[str]:
        """`python -m <pkg> <args>` with <pkg> resolved from the project.

        `<pkg>` is discovered deterministically from `self._root`
        (src-layout package or the declared wheel target), never guessed.
        Requires a root-bound adapter — the registry singleton (no root)
        is for detection/discovery, not run-smoke.
        """
        if self._root is None:
            raise ValueError("run_smoke needs a project root: construct PythonCliAdapter(root=...)")
        pkg = resolve_pkg(self._root)
        return ["python", "-m", pkg, *(args.split() if args else [])]

    def acceptance_spec(self, task: object) -> tuple[str, str] | None:
        # Default-floor: the deliverable is `-m`-runnable and --help exits
        # cleanly. The expected observable is exit-0 (empty-string sentinel
        # the gate treats as "command must succeed"); a richer round-trip
        # spec is feat/acceptance-spec-in-tasks.
        return (f"python -m <pkg> {_DEFAULT_FLOOR_HELP_ARGS}", "")

    def scaffold(self, spec: ScaffoldSpec) -> list[Path]:
        """Emit a deterministic, `-m`-runnable python-cli skeleton.

        Creates `src/<pkg>/__init__.py`, `src/<pkg>/__main__.py`, and a
        `pyproject.toml` with the hatchling src-layout wheel target. Never
        overwrites existing files (fails loud via _ensure_absent); rejects
        invalid package names before writing anything.
        """
        if not _PKG_NAME_RE.match(spec.pkg):
            raise ValueError(
                f"invalid python package name {spec.pkg!r}: "
                "must be a valid identifier (letters, digits, underscore; no leading digit)"
            )

        pkg_dir = spec.root / "src" / spec.pkg
        init_py = pkg_dir / "__init__.py"
        main_py = pkg_dir / "__main__.py"
        pyproject = spec.root / "pyproject.toml"

        # Clobber guard BEFORE any write — a half-written skeleton on top
        # of user code is the failure path scenarios 8/9 forbid.
        for target in (init_py, main_py, pyproject):
            _ensure_absent(target)

        pkg_dir.mkdir(parents=True, exist_ok=True)
        init_py.write_text(_INIT_TEMPLATE, encoding="utf-8")
        main_py.write_text(_MAIN_TEMPLATE, encoding="utf-8")
        pyproject.write_text(_pyproject_template(spec.pkg), encoding="utf-8")
        return [init_py, main_py, pyproject]


def _ensure_absent(path: Path) -> None:
    if path.exists():
        raise FileExistsError(
            f"scaffold refuses to overwrite existing file: {path} "
            "(scaffold a fresh project dir or remove the file first)"
        )


_INIT_TEMPLATE = '''"""Scaffolded python-cli package."""
'''

# `__main__.py` is what makes `python -m <pkg>` runnable — a
# [project.scripts] console entry alone does NOT (runpy executes
# <pkg>/__main__). See stack-notes "python -m <pkg> invocation contract".
_MAIN_TEMPLATE = '''"""Entrypoint for `python -m <pkg>`."""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if "--help" in args or "-h" in args:
        print("usage: <pkg> [--help]")
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
'''


def _pyproject_template(pkg: str) -> str:
    # hatchling src-layout: the wheel target MUST name `src/<pkg>` or
    # metadata generation fails. See stack-notes "hatchling / src-layout".
    return f"""[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "{pkg.replace("_", "-")}"
version = "0.0.0"
requires-python = ">=3.11"

[tool.hatch.build.targets.wheel]
packages = ["src/{pkg}"]
"""
