"""Tests for the SkillRegistry — built-in skills, detection, registration."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.skills import (
    DockerSkill,
    PythonSkill,
    Skill,
    SkillRegistry,
    active_skills,
    default_skill,
    get_skill,
    register_skill,
)

# ── PythonSkill.detect ───────────────────────────────────────────────────────


def test_python_skill_detects_pyproject_toml(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'x'\n")
    assert PythonSkill().detect(tmp_path) is True


def test_python_skill_detects_requirements_txt(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("pytest\n")
    assert PythonSkill().detect(tmp_path) is True


def test_python_skill_detects_setup_py(tmp_path: Path) -> None:
    (tmp_path / "setup.py").write_text("from setuptools import setup\nsetup()\n")
    assert PythonSkill().detect(tmp_path) is True


def test_python_skill_no_detect_empty_dir(tmp_path: Path) -> None:
    assert PythonSkill().detect(tmp_path) is False


# ── DockerSkill.detect ───────────────────────────────────────────────────────


def test_docker_skill_detects_dockerfile(tmp_path: Path) -> None:
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\n")
    assert DockerSkill().detect(tmp_path) is True


def test_docker_skill_detects_compose_yml(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services:\n  app: {}\n")
    assert DockerSkill().detect(tmp_path) is True


def test_docker_skill_no_detect_empty_dir(tmp_path: Path) -> None:
    assert DockerSkill().detect(tmp_path) is False


# ── command shapes ───────────────────────────────────────────────────────────


def test_python_skill_test_cmd_default() -> None:
    cmd = PythonSkill().test_cmd()
    assert cmd[0] == "pytest"
    assert "-x" in cmd
    assert "--tb=short" in cmd
    assert "-q" in cmd


def test_python_skill_test_cmd_appends_args() -> None:
    cmd = PythonSkill().test_cmd("-k 'foo or bar'")
    # shlex-parsed: the quoted segment becomes a single argv element.
    assert "foo or bar" in cmd
    assert "-k" in cmd


def test_python_skill_lint_cmd_shape() -> None:
    assert PythonSkill().lint_cmd() == ["ruff", "check", "."]


def test_python_skill_format_cmd_shape() -> None:
    assert PythonSkill().format_cmd() == ["ruff", "format", "."]


def test_docker_skill_test_cmd_shape() -> None:
    cmd = DockerSkill().test_cmd()
    assert cmd[:5] == ["docker", "compose", "run", "--rm", "app"]
    assert "pytest" in cmd


def test_docker_skill_no_formatter() -> None:
    assert DockerSkill().format_cmd() is None


# ── SkillRegistry.active / default ───────────────────────────────────────────


def test_registry_active_returns_python_and_docker(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "Dockerfile").write_text("FROM python:3.11\n")
    reg = SkillRegistry()
    reg.register(PythonSkill())
    reg.register(DockerSkill())
    active = reg.active(tmp_path)
    names = [s.name for s in active]
    assert names == ["python", "docker"]


def test_registry_default_returns_python_for_python_project(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    reg = SkillRegistry()
    reg.register(PythonSkill())
    reg.register(DockerSkill())
    d = reg.default(tmp_path)
    assert d is not None
    assert d.name == "python"


def test_registry_default_none_when_nothing_detects(tmp_path: Path) -> None:
    reg = SkillRegistry()
    reg.register(PythonSkill())
    assert reg.default(tmp_path) is None


# ── register_skill picks up custom skills ────────────────────────────────────


class _DummySkill(Skill):
    name = "dummy"
    description = "dummy skill for testing register_skill()"

    def detect(self, root: Path) -> bool:
        return (root / ".dummy-marker").is_file()

    def test_cmd(self, args: str = "") -> list[str]:
        return ["echo", "dummy-test"]

    def lint_cmd(self) -> list[str]:
        return ["echo", "dummy-lint"]


def test_register_skill_picks_up_custom_skill(tmp_path: Path) -> None:
    (tmp_path / ".dummy-marker").touch()
    register_skill(_DummySkill())
    try:
        active = active_skills(tmp_path)
        names = [s.name for s in active]
        assert "dummy" in names
        assert get_skill("dummy") is not None
    finally:
        # Cleanup — the registry is module-global; leaving the dummy
        # behind would leak into the test_app.py /skills assertion.
        from code_scalpel.skills import _registry

        _registry._skills = [s for s in _registry._skills if s.name != "dummy"]


# ── token_cost ──────────────────────────────────────────────────────────────


def test_skill_token_cost_reasonable() -> None:
    """Token cost is len(name+description)/4 — should sit in single/low
    double digits for descriptions ~50–150 chars long."""
    for skill in (PythonSkill(), DockerSkill()):
        cost = skill.token_cost()
        assert cost > 0
        assert cost < 100, f"{skill.name} token_cost={cost} looks too high"


# ── default_skill / active_skills against the real registry ──────────────────


def test_module_level_default_skill_returns_python(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    d = default_skill(tmp_path)
    assert d is not None
    assert d.name == "python"


def test_skill_is_abc_cannot_instantiate_bare() -> None:
    """Skill is an ABC — direct instantiation must fail; subclasses
    must implement detect/test_cmd/lint_cmd."""
    with pytest.raises(TypeError):
        Skill()  # type: ignore[abstract]
