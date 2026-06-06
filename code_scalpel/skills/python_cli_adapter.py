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
never selected by `default_runnable` — the existing PythonSkill stays the
test runner.

Why `hidden = True`: the adapter shares PythonSkill's detect(), so on a
Python project it would otherwise show up as a second, duplicate row in
the model catalog (`all_skills`), the detected-stack hint, and the
`/skills` panel — and there is no `prompts/skills/python-cli.md`, so a
model that `load_skill('python-cli')` would get empty guidance and miss
python.md's pytest/ruff instructions. `hidden` keeps it out of every
model-facing listing while leaving it `get_skill('python-cli')`-
discoverable for the future run-loop that constructs it deliberately.

Determinism is the point: the `__main__.py` entrypoint and the hatchling
src-layout config are code-owned here, not emitted by the model's whim
(the documented `notes_cli` coin-flip).
"""

from __future__ import annotations

import re
import shlex
from pathlib import Path

from code_scalpel.skills.base import (
    AcceptanceArgError,
    AcceptanceSpec,
    ScaffoldSpec,
    Skill,
    decode_derived_acceptance,
)
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
    # Owns the python-cli acceptance/run-smoke contract — the run-loop's
    # verification #4 selects this adapter via `acceptance_adapter`.
    provides_acceptance = True
    # Excluded from every model-facing listing (catalog / detected hint /
    # /skills) while staying get_skill-discoverable. See module docstring.
    hidden = True

    def __init__(self, root: Path | None = None) -> None:
        # `root` lets an adapter instance resolve <pkg> deterministically
        # for run_smoke. The registry constructs it with no root (a
        # detection/discovery singleton); a caller that wants run_smoke
        # constructs PythonCliAdapter(root=project_root).
        self._root = root
        # One PythonSkill instance the adapter delegates detect/test/lint
        # to — a python-cli project IS a Python project, so the adapter
        # reuses PythonSkill verbatim instead of duplicating its commands.
        self._py = PythonSkill()

    def bind(self, root: Path) -> Skill:
        """Return a root-bound adapter so `run_smoke`/`acceptance_spec` resolve.

        The registry holds a rootless discovery singleton (detect only); the
        run-loop binds it to the project root before asking for the run-smoke
        command, so `<pkg>` resolves deterministically instead of raising.
        """
        return PythonCliAdapter(root=root)

    def detect(self, root: Path) -> bool:
        return self._py.detect(root)

    def test_cmd(self, args: str = "") -> list[str]:
        return self._py.test_cmd(args)

    def lint_cmd(self) -> list[str]:
        return self._py.lint_cmd()

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
        # shlex.split (not str.split) for parity with test_cmd — keeps
        # quoted argument groups like `--note 'a b'` intact. A malformed args
        # string (unbalanced quotes) is a SPEC error, not a package error:
        # re-raise as AcceptanceArgError so the run-loop falls back to the
        # floor instead of mislabeling a healthy package `pkg-unresolvable`
        # (review finding 5).
        try:
            split_args = shlex.split(args) if args else []
        except ValueError as exc:
            raise AcceptanceArgError(f"cannot tokenize acceptance args {args!r}: {exc}") from exc
        return ["python", "-m", pkg, *split_args]

    def acceptance_spec(self, task: object) -> AcceptanceSpec | None:
        """Precedence C (narrow-pass-derived) → A (default-floor).

        The EXECUTED spec is always the derived (C, args-only) or floor (A)
        one. A human-declared acceptance is PROSE intent, not a CLI command —
        it is fed to the derivation as a hint (in the pre-loop pass) and never
        executed as argv (review finding 2: prose B must not be run as
        `python -m <pkg> the note appears in the list`, which would error and
        false-demote the task every run). So a task with prose acceptance but
        no derived marker falls through to the observational floor, never
        demoted. The derived spec's `command` is built through `run_smoke(args)`
        so the python-specific `python -m <pkg>` prefix lives only here and the
        model-supplied `args` is tokenized into argv, never a shell string
        (KD3 args-only). The rootless discovery singleton cannot resolve a
        package — the same `ValueError` `run_smoke` raises bubbles up so the
        run-loop records `pkg-unresolvable` rather than running a placeholder.
        """
        if self._root is None:
            raise ValueError(
                "acceptance_spec needs a project root: construct PythonCliAdapter(root=...)"
            )
        bullets = tuple(getattr(task, "acceptance", ()))
        derived = self._derived_spec(bullets)
        if derived is not None:
            return derived
        return self._floor_spec()

    def acceptance_applicable(self, task: object) -> bool:
        """Enforcement-applicability WITHOUT building the command (no run_smoke /
        resolve_pkg). The single source of the C→A precedence rule for callers
        that need only the gate, not the command — e.g. the run-loop's
        `pkg-unresolvable` path, where argv assembly already raised (review
        finding 6, unifies the dual source). A decodable derived marker carries
        its own `applicable`; everything else (empty, prose, malformed marker)
        is the observational floor — not applicable.
        """
        for line in tuple(getattr(task, "acceptance", ())):
            data = decode_derived_acceptance(line)
            if data is not None:
                return bool(data.get("applicable", False))
        return False

    def _derived_spec(self, bullets: tuple[str, ...]) -> AcceptanceSpec | None:
        """Build the C (narrow-pass-derived) spec from a written-back marker.

        Returns None when no DECODABLE derived marker is present (so the caller
        falls through to A). A marker-prefixed-but-undecodable line is ignored
        (treated as absent → floor), never fed as args (review finding 4). A
        derived not-applicable result yields a spec with `applicable=False` —
        persisted so it is never re-derived, observed not enforced.
        """
        for line in bullets:
            data = decode_derived_acceptance(line)
            if data is None:
                continue
            args = str(data.get("args", ""))
            expected = str(data.get("expected", ""))
            applicable = bool(data.get("applicable", False))
            return AcceptanceSpec(
                command=self._command(args),
                expected=expected,
                applicable=applicable,
                source="derived",
            )
        return None

    def _floor_spec(self) -> AcceptanceSpec:
        """Build the A (default-floor) spec: `python -m <pkg> --help`, exit-0
        only, NEVER applicable — the structural lock that keeps a python
        library (which `detect` over-fires on) observational, not demoted.
        """
        return AcceptanceSpec(
            command=self._command(_DEFAULT_FLOOR_HELP_ARGS),
            expected="",
            applicable=False,
            source="floor",
        )

    def _command(self, args: str) -> str:
        return shlex.join(self.run_smoke(args))

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
