"""Tests for the SkillRegistry — built-in skills, detection, registration."""

from __future__ import annotations

from pathlib import Path

import pytest

from code_scalpel.skills import (
    DockerSkill,
    GoSkill,
    JsTsSkill,
    PostgresSkill,
    PythonSkill,
    Skill,
    SkillRegistry,
    SqliteSkill,
    active_skills,
    default_runnable_skill,
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


# ── JsTsSkill ────────────────────────────────────────────────────────────────


def test_js_skill_detects_package_json(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text('{"name": "x"}')
    assert JsTsSkill().detect(tmp_path) is True


def test_js_skill_no_detect_empty(tmp_path: Path) -> None:
    assert JsTsSkill().detect(tmp_path) is False


def test_js_skill_test_cmd_shape() -> None:
    cmd = JsTsSkill().test_cmd()
    assert cmd[0] in ("npm", "pnpm", "yarn")
    assert "test" in cmd


def test_js_skill_test_cmd_appends_args_via_dashdash() -> None:
    """Extra args must go after `--` so the package manager passes them
    to the test script, not to itself."""
    cmd = JsTsSkill().test_cmd("--watch")
    assert "--" in cmd
    assert cmd.index("--") < cmd.index("--watch")


# ── GoSkill ──────────────────────────────────────────────────────────────────


def test_go_skill_detects_go_mod(tmp_path: Path) -> None:
    (tmp_path / "go.mod").write_text("module example.com/x\n\ngo 1.22\n")
    assert GoSkill().detect(tmp_path) is True


def test_go_skill_no_detect_empty(tmp_path: Path) -> None:
    assert GoSkill().detect(tmp_path) is False


def test_go_skill_test_cmd_defeats_cache() -> None:
    """`-count=1` is the standard cache-busting incantation — without it
    the agent's "re-run tests after patch" would see stale PASS."""
    cmd = GoSkill().test_cmd()
    assert "-count=1" in cmd
    assert cmd[0] == "go" and cmd[1] == "test"
    assert cmd[-1] == "./..."


def test_go_skill_lint_and_format() -> None:
    assert GoSkill().lint_cmd() == ["go", "vet", "./..."]
    assert GoSkill().format_cmd() == ["gofmt", "-w", "."]


# ── PostgresSkill (component) ────────────────────────────────────────────────


def test_postgres_skill_provides_no_test_runner() -> None:
    """PostgresSkill is detection-only — it must opt out of the test
    path so it never overrides the language skill."""
    assert PostgresSkill().provides_test_runner is False


def test_postgres_skill_detects_alembic(tmp_path: Path) -> None:
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    assert PostgresSkill().detect(tmp_path) is True


def test_postgres_skill_detects_compose_with_postgres(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services:\n  db:\n    image: postgres:16\n")
    assert PostgresSkill().detect(tmp_path) is True


def test_postgres_skill_compose_without_postgres_does_not_trip(tmp_path: Path) -> None:
    """Generic docker-compose (no postgres image) must NOT fire — false
    positive would surface Postgres on a plain Redis/Nginx stack."""
    (tmp_path / "docker-compose.yml").write_text("services:\n  cache:\n    image: redis:7\n")
    assert PostgresSkill().detect(tmp_path) is False


def test_postgres_skill_detects_database_url_in_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("DATABASE_URL=postgresql://user:pass@host/db\n")
    assert PostgresSkill().detect(tmp_path) is True


def test_postgres_skill_detects_sql_migrations(tmp_path: Path) -> None:
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "0001_init.sql").write_text("CREATE TABLE users(id INT);\n")
    assert PostgresSkill().detect(tmp_path) is True


def test_postgres_skill_no_detect_empty(tmp_path: Path) -> None:
    assert PostgresSkill().detect(tmp_path) is False


def test_postgres_skill_test_cmd_empty() -> None:
    """Component skill — empty test_cmd signals "no runner here"."""
    assert PostgresSkill().test_cmd() == []


# ── SqliteSkill (component) ──────────────────────────────────────────────────


def test_sqlite_skill_provides_no_test_runner() -> None:
    assert SqliteSkill().provides_test_runner is False


def test_sqlite_skill_detects_db_file(tmp_path: Path) -> None:
    (tmp_path / "app.db").write_bytes(b"SQLite format 3\x00")
    assert SqliteSkill().detect(tmp_path) is True


def test_sqlite_skill_detects_sqlite3_extension(tmp_path: Path) -> None:
    (tmp_path / "data.sqlite3").write_bytes(b"SQLite format 3\x00")
    assert SqliteSkill().detect(tmp_path) is True


def test_sqlite_skill_detects_schema_sql(tmp_path: Path) -> None:
    (tmp_path / "schema.sql").write_text("CREATE TABLE x(id INT);\n")
    assert SqliteSkill().detect(tmp_path) is True


def test_sqlite_skill_no_detect_empty(tmp_path: Path) -> None:
    assert SqliteSkill().detect(tmp_path) is False


# ── default_runnable_skill: polyglot priority ────────────────────────────────


def test_default_runnable_skips_component_skills(tmp_path: Path) -> None:
    """Python + Postgres repo — runnable lookup must return Python,
    not Postgres. Otherwise `_tool_run_tests` would dispatch through
    an empty cmd and fail to run any tests."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname='x'\n")
    (tmp_path / "alembic.ini").write_text("[alembic]\n")

    detected = active_skills(tmp_path)
    names = [s.name for s in detected]
    assert "python" in names and "postgres" in names  # both surface

    runnable = default_runnable_skill(tmp_path)
    assert runnable is not None
    assert runnable.name == "python"


def test_default_runnable_returns_none_on_component_only_dir(tmp_path: Path) -> None:
    """A repo that's pure Postgres (alembic config only, no language
    markers) has no runnable skill — caller falls back to bare pytest."""
    (tmp_path / "alembic.ini").write_text("[alembic]\n")
    assert default_runnable_skill(tmp_path) is None
