"""Tests for `resolve_pkg` — the deterministic run-smoke target resolver.

Gap A of `feat/flat-layout-run-smoke`: `resolve_pkg(root)` returns a typed
`RunTarget(kind, target)` carrying both the argv shape (`module` / `script`)
and the target, resolved through a fixed precedence ladder where declared
(pyproject) shapes outrank discovered (filesystem) shapes. Ambiguity at any
rung and absence of all rungs both raise `ValueError` (never guess).

Covers the plan's Test plan (resolution shapes): root package with
`__main__.py`, root script, `[project.scripts]` entry, src-layout (regression),
hatchling target (regression), ambiguous root scripts, absence, the
malformed-pyproject fall-through, and the declared-outranks-discovered
stack-spec test (entry-points spec URL in the test body).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.skills.python_pkg import RunTarget, resolve_pkg

_HATCHLING = (
    "[build-system]\nrequires=['hatchling']\nbuild-backend='hatchling.build'\n"
    "[project]\nname='x'\nversion='0'\n"
)


def _make_root_package(root: Path, pkg: str) -> None:
    pkg_dir = root / pkg
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "__main__.py").write_text("")


def _make_src_package(root: Path, pkg: str) -> None:
    pkg_dir = root / "src" / pkg
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "__main__.py").write_text("")


# ── discovered shapes (filesystem) ───────────────────────────────────────────


def test_resolve_root_package_with_main(tmp_path: Path) -> None:
    """A root-level package dir with `__main__.py` (no src/, no pyproject) →
    `(module, <pkg>)` so the adapter builds `python -m <pkg>`."""
    _make_root_package(tmp_path, "notes_cli")
    assert resolve_pkg(tmp_path) == RunTarget(kind="module", target="notes_cli")


def test_resolve_root_script(tmp_path: Path) -> None:
    """A single root entry script from the candidate list (no package) →
    `(script, "cli.py")` so the adapter builds `python cli.py`."""
    (tmp_path / "cli.py").write_text("print('hi')\n")
    assert resolve_pkg(tmp_path) == RunTarget(kind="script", target="cli.py")


def test_resolve_src_layout_unchanged(tmp_path: Path) -> None:
    """Regression: an `src/<pkg>` layout still resolves to `(module, <pkg>)`."""
    _make_src_package(tmp_path, "myapp")
    assert resolve_pkg(tmp_path) == RunTarget(kind="module", target="myapp")


# ── declared shapes (pyproject) ──────────────────────────────────────────────


def test_resolve_hatchling_target_unchanged(tmp_path: Path) -> None:
    """Regression: a hatchling wheel target still resolves to `(module, <pkg>)`."""
    (tmp_path / "pyproject.toml").write_text(
        _HATCHLING + "[tool.hatch.build.targets.wheel]\npackages=['src/myapp']\n"
    )
    assert resolve_pkg(tmp_path) == RunTarget(kind="module", target="myapp")


def test_resolve_project_scripts_entry(tmp_path: Path) -> None:
    """A single `[project.scripts]` console entry resolves to the entry's
    module as a `module` target."""
    (tmp_path / "pyproject.toml").write_text(
        _HATCHLING + "[project.scripts]\nnotes = 'notes_cli.app:main'\n"
    )
    assert resolve_pkg(tmp_path) == RunTarget(kind="module", target="notes_cli.app")


def test_declared_entry_outranks_discovered(tmp_path: Path) -> None:
    """Stack-spec: a `[project.scripts]` entry is chosen over a filesystem root
    script — declared outranks discovered. Verified against the entry-points
    spec, not a self-consistent mapping:
    https://packaging.python.org/en/latest/specifications/entry-points/
    """
    # Both present: a declared console entry AND a discoverable root script.
    (tmp_path / "cli.py").write_text("print('hi')\n")
    (tmp_path / "pyproject.toml").write_text(
        _HATCHLING + "[project.scripts]\nnotes = 'notes_cli:main'\n"
    )
    # The declaration wins: module target, NOT the script.
    assert resolve_pkg(tmp_path) == RunTarget(kind="module", target="notes_cli")


def test_hatchling_outranks_project_scripts(tmp_path: Path) -> None:
    """Within declared shapes: the hatchling wheel target outranks a
    `[project.scripts]` entry (the project's own ship declaration first)."""
    (tmp_path / "pyproject.toml").write_text(
        _HATCHLING
        + "[project.scripts]\nnotes = 'other.app:main'\n"
        + "[tool.hatch.build.targets.wheel]\npackages=['src/notes_cli']\n"
    )
    assert resolve_pkg(tmp_path) == RunTarget(kind="module", target="notes_cli")


def test_root_package_outranks_root_script(tmp_path: Path) -> None:
    """A discovered root package with `__main__.py` outranks a root script:
    a package is a stronger intent signal than a bare script."""
    _make_root_package(tmp_path, "notes_cli")
    (tmp_path / "cli.py").write_text("print('hi')\n")
    assert resolve_pkg(tmp_path) == RunTarget(kind="module", target="notes_cli")


# ── ambiguity → raise (never guess) ──────────────────────────────────────────


def test_resolve_ambiguous_root_scripts_raises(tmp_path: Path) -> None:
    """Two root scripts from the candidate list, no declared entry → raise
    (never pick one by candidate order)."""
    (tmp_path / "main.py").write_text("")
    (tmp_path / "cli.py").write_text("")
    with pytest.raises(ValueError, match="ambiguous root entry scripts"):
        resolve_pkg(tmp_path)


def test_resolve_ambiguous_root_packages_raises(tmp_path: Path) -> None:
    """Two root packages each with `__main__.py` → raise."""
    _make_root_package(tmp_path, "app_a")
    _make_root_package(tmp_path, "app_b")
    with pytest.raises(ValueError, match="ambiguous root packages"):
        resolve_pkg(tmp_path)


def test_resolve_ambiguous_hatchling_target_raises(tmp_path: Path) -> None:
    """Two hatchling wheel-target packages → raise (declared but no single
    intent)."""
    (tmp_path / "pyproject.toml").write_text(
        _HATCHLING + "[tool.hatch.build.targets.wheel]\npackages=['src/a','src/b']\n"
    )
    with pytest.raises(ValueError, match="ambiguous hatchling"):
        resolve_pkg(tmp_path)


def test_resolve_ambiguous_project_scripts_raises(tmp_path: Path) -> None:
    """Two `[project.scripts]` console entries → raise."""
    (tmp_path / "pyproject.toml").write_text(
        _HATCHLING + "[project.scripts]\na = 'pkg_a:main'\nb = 'pkg_b:main'\n"
    )
    with pytest.raises(ValueError, match="ambiguous \\[project.scripts\\]"):
        resolve_pkg(tmp_path)


# ── absence + failure paths ──────────────────────────────────────────────────


def test_resolve_absence_raises(tmp_path: Path) -> None:
    """An empty / library project (no runnable at any rung) → ValueError →
    the run-loop records `pkg-unresolvable` (unchanged contract)."""
    with pytest.raises(ValueError, match="cannot resolve a python-cli run target"):
        resolve_pkg(tmp_path)


def test_resolve_no_runnable_raises_pkg_unresolvable(tmp_path: Path) -> None:
    """Failure path 10: a src/ package that is NOT a package (no __init__.py)
    and nothing else runnable → absence → ValueError."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "not_a_pkg").mkdir()  # no __init__.py
    with pytest.raises(ValueError):
        resolve_pkg(tmp_path)


def test_resolve_malformed_pyproject_falls_through(tmp_path: Path) -> None:
    """Failure path 9: an invalid `pyproject.toml` is treated as 'no declared
    target' — resolution falls through to filesystem discovery, never crashes."""
    (tmp_path / "pyproject.toml").write_text("this is { not valid toml ===\n")
    _make_root_package(tmp_path, "notes_cli")
    # Despite the broken pyproject, the discovered root package resolves.
    assert resolve_pkg(tmp_path) == RunTarget(kind="module", target="notes_cli")


def test_resolve_unreadable_pyproject_falls_through(tmp_path: Path) -> None:
    """A pyproject with no relevant declarations falls through to discovery."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\nversion='0'\n")
    (tmp_path / "cli.py").write_text("")
    assert resolve_pkg(tmp_path) == RunTarget(kind="script", target="cli.py")


def test_resolve_custom_candidate_list(tmp_path: Path) -> None:
    """The candidate list is a parameter (config-owned): a non-default name
    resolves only when passed in."""
    (tmp_path / "run.py").write_text("")
    # Default list does not include run.py → absence.
    with pytest.raises(ValueError):
        resolve_pkg(tmp_path)
    # Passed in → resolves.
    assert resolve_pkg(tmp_path, ["run.py"]) == RunTarget(kind="script", target="run.py")
