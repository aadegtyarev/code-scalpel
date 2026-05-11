"""DockerSkill — demo of a compose-style component skill.

Docker projects don't have a canonical lint, so `lint_cmd` returns the
empty list (the registry treats this as "skill has no lint"). The test
command assumes a service named `app` — that's the de-facto convention
in scaffolding tools (cookiecutter-django, FastAPI templates, etc.).
Real projects with a different service name will override or replace
this skill via `register_skill`.

This ships mainly as proof that the registry handles more than one
skill type. The first real value comes when a Compose project also has
a `pyproject.toml` and both PythonSkill and DockerSkill detect — the
TUI can then surface both in /skills, and a future `run_tests` can
choose between them.
"""

from __future__ import annotations

import shlex
from pathlib import Path

from code_scalpel.skills.base import Skill


class DockerSkill(Skill):
    name = "docker"
    description = "docker compose run app pytest (detects Dockerfile / docker-compose.yml)."

    def detect(self, root: Path) -> bool:
        for marker in ("Dockerfile", "docker-compose.yml", "docker-compose.yaml", "compose.yml"):
            if (root / marker).is_file():
                return True
        return False

    def test_cmd(self, args: str = "") -> list[str]:
        extra = shlex.split(args) if args else []
        return ["docker", "compose", "run", "--rm", "app", "pytest", *extra]

    def lint_cmd(self) -> list[str]:
        # Docker has no canonical lint command — hadolint is one option,
        # but it's not installed by default and a real user would wire
        # it via a custom skill. Returning [] tells the registry "skip
        # lint for this one"; the /skills view renders it as "no lint".
        return []

    def format_cmd(self) -> list[str] | None:
        return None
