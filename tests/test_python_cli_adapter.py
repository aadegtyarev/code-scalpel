"""Tests for PythonCliAdapter and the ProjectAdapter superset of Skill.

Covers the plan's Test plan: the ABC defaults are non-abstract (no
existing skill becomes abstract), PythonCliAdapter's build/test/run-smoke/
acceptance shapes, deterministic package resolution, the scaffold
execution + failure paths, and the registry no-hijack interaction.
"""

from __future__ import annotations

import subprocess
import sys
import tomllib
from pathlib import Path

import pytest

from code_scalpel.skills import (
    DockerSkill,
    GoSkill,
    JsTsSkill,
    PostgresSkill,
    PythonCliAdapter,
    PythonSkill,
    ScaffoldSpec,
    Skill,
    SqliteSkill,
    default_runnable_skill,
    get_skill,
)

# ── ABC defaults are non-abstract (scenario 1) ───────────────────────────────


def test_existing_skills_still_instantiate() -> None:
    """Adding the four ProjectAdapter methods must not turn any existing
    concrete skill abstract — each must still construct unchanged."""
    for skill in (
        PythonSkill(),
        GoSkill(),
        JsTsSkill(),
        DockerSkill(),
        PostgresSkill(),
        SqliteSkill(),
    ):
        assert isinstance(skill, Skill)


def test_base_defaults() -> None:
    """A minimal skill that overrides nothing returns the documented
    safe defaults for all four new methods."""

    class _Bare(Skill):
        name = "bare-adapter"
        description = "bare"

        def detect(self, root: Path) -> bool:
            return False

        def test_cmd(self, args: str = "") -> list[str]:
            return []

        def lint_cmd(self) -> list[str]:
            return []

    s = _Bare()
    assert s.build_install() == []
    assert s.run_smoke() == []
    assert s.acceptance_spec(task=None) is None
    assert s.scaffold(ScaffoldSpec(root=Path("/nonexistent"), pkg="x")) == []


# ── PythonCliAdapter basics (scenarios 2, 3, 4) ──────────────────────────────


def test_python_cli_adapter_detect(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    assert PythonCliAdapter().detect(tmp_path) is True

    empty = tmp_path / "empty"
    empty.mkdir()
    assert PythonCliAdapter().detect(empty) is False


def test_python_cli_adapter_build_install() -> None:
    assert PythonCliAdapter().build_install() == ["pip", "install", "-e", "."]


def test_python_cli_adapter_test_matches_python_skill() -> None:
    """test() must equal PythonSkill.test_cmd() — no behavior drift."""
    adapter = PythonCliAdapter()
    assert adapter.test() == PythonSkill().test_cmd()
    assert adapter.test("-k foo") == PythonSkill().test_cmd("-k foo")
    assert adapter.test_cmd() == PythonSkill().test_cmd()


def test_python_cli_adapter_run_smoke(tmp_path: Path) -> None:
    _make_src_pkg(tmp_path, "myapp")
    adapter = PythonCliAdapter(root=tmp_path)
    assert adapter.run_smoke("add x") == ["python", "-m", "myapp", "add", "x"]


def test_run_smoke_pkg_resolution(tmp_path: Path) -> None:
    """<pkg> is resolved from the project's actual src package, not a
    hardcoded guess or the literal 'src'."""
    _make_src_pkg(tmp_path, "notes_cli")
    adapter = PythonCliAdapter(root=tmp_path)
    cmd = adapter.run_smoke("list")
    assert cmd[:3] == ["python", "-m", "notes_cli"]
    assert "src" not in cmd


def test_run_smoke_without_root_is_clear_error() -> None:
    with pytest.raises(ValueError, match="project root"):
        PythonCliAdapter().run_smoke("add x")


def test_acceptance_spec_default_floor() -> None:
    spec = PythonCliAdapter().acceptance_spec(task=None)
    assert spec is not None
    command, _expected = spec
    assert "python -m" in command
    assert "--help" in command


# ── scaffold execution + failure paths (scenarios 5, 8, 9) ───────────────────


def test_scaffold_smoke(tmp_path: Path) -> None:
    """Scaffold a temp project, then ACTUALLY run `python -m <pkg>`
    against it and assert it executes without an import/packaging error.

    This proves the scaffold emits a `-m`-runnable entrypoint and kills
    the documented `__main__.py` coin-flip. `python -m <pkg>` requires a
    `__main__.py` in the package (a [project.scripts] console entry does
    NOT make `-m` work) and the hatchling wheel target must name the
    src-layout package, per the cited stack-notes rules:
      - Python __main__ / runpy: https://docs.python.org/3/library/__main__.html#main-py-in-python-packages
                                 https://docs.python.org/3/library/runpy.html
      - hatchling build config:  https://hatch.pypa.io/latest/config/build/#packages
    """
    adapter = PythonCliAdapter()
    written = adapter.scaffold(ScaffoldSpec(root=tmp_path, pkg="notes_cli"))
    assert (tmp_path / "src" / "notes_cli" / "__main__.py") in written

    # Run the deliverable as `python -m notes_cli` with src on the path
    # (the runnability check; not a full install). A missing/broken
    # __main__.py would raise "No module named ... .__main__" / nonzero.
    result = subprocess.run(
        [sys.executable, "-m", "notes_cli", "--help"],
        cwd=tmp_path / "src",
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


def test_scaffold_pyproject_has_src_layout_wheel_target(tmp_path: Path) -> None:
    """hatchling src-layout: the wheel target must name src/<pkg>, else
    metadata generation fails (stack-notes hatchling rule)."""
    PythonCliAdapter().scaffold(ScaffoldSpec(root=tmp_path, pkg="notes_cli"))
    data = tomllib.loads((tmp_path / "pyproject.toml").read_text())
    packages = data["tool"]["hatch"]["build"]["targets"]["wheel"]["packages"]
    assert packages == ["src/notes_cli"]


def test_scaffold_does_not_clobber(tmp_path: Path) -> None:
    """Scaffold into a dir with an existing source file must NOT
    overwrite it — fail loud, never silent (scenario 8)."""
    pkg_dir = tmp_path / "src" / "notes_cli"
    pkg_dir.mkdir(parents=True)
    sentinel = pkg_dir / "__init__.py"
    sentinel.write_text("# user code — do not touch\n")

    with pytest.raises(FileExistsError):
        PythonCliAdapter().scaffold(ScaffoldSpec(root=tmp_path, pkg="notes_cli"))

    assert sentinel.read_text() == "# user code — do not touch\n"


@pytest.mark.parametrize("bad", ["", "1bad", "has-dash", "has space", "a.b"])
def test_scaffold_invalid_pkg_name(tmp_path: Path, bad: str) -> None:
    """Invalid/empty package name fails clearly with no half-written
    skeleton on disk (scenario 9)."""
    with pytest.raises(ValueError, match="invalid python package name"):
        PythonCliAdapter().scaffold(ScaffoldSpec(root=tmp_path, pkg=bad))
    # Nothing written.
    assert not (tmp_path / "src").exists()
    assert not (tmp_path / "pyproject.toml").exists()


# ── registry interaction: discoverable without hijacking test path ───────────


def test_registry_default_runner_unchanged_after_adapter_registered(tmp_path: Path) -> None:
    """Drives the PRODUCTION registry: PythonCliAdapter is registered at
    import, yet default_runnable for a Python project still resolves to
    the PythonSkill test runner (no hijack). The adapter is discoverable
    via get_skill but never wins the test path."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")

    runnable = default_runnable_skill(tmp_path)
    assert runnable is not None
    assert runnable.name == "python"
    assert runnable.test_cmd() == PythonSkill().test_cmd()

    # Discoverable, but provides_test_runner = False keeps it off the path.
    adapter = get_skill("python-cli")
    assert isinstance(adapter, PythonCliAdapter)
    assert adapter.provides_test_runner is False


def _make_src_pkg(root: Path, pkg: str) -> None:
    pkg_dir = root / "src" / pkg
    pkg_dir.mkdir(parents=True)
    (pkg_dir / "__init__.py").write_text("")
    (pkg_dir / "__main__.py").write_text("")
    (root / "pyproject.toml").write_text(
        "[build-system]\nrequires=['hatchling']\nbuild-backend='hatchling.build'\n"
        "[project]\nname='x'\nversion='0'\n"
        f"[tool.hatch.build.targets.wheel]\npackages=['src/{pkg}']\n"
    )
