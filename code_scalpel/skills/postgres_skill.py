"""PostgresSkill — component skill marking that the project uses Postgres.

Component skills detect the stack so the TUI's `/skills` view shows
"this repo uses Postgres" and so future runtime-integration can load
Postgres-flavoured context (psql command shape, migration conventions),
but they own no test runner — `provides_test_runner = False` keeps the
agent's `_tool_run_tests` dispatching to the language skill (Python,
JS, Go) instead.

Detection heuristics, in priority order:
  • `alembic.ini` — SQLAlchemy + Alembic, overwhelmingly Postgres in
    practice;
  • `docker-compose.y*ml` mentioning `postgres` — the canonical
    "Postgres-in-dev" setup;
  • `.env` carrying a `postgres://` or `postgresql://` URL;
  • `*.sql` under a `migrations/` or `db/migrations/` directory —
    plain SQL migration shape (golang-migrate, sqlx, dbmate, etc.).

False positives are cheap (a wrong "/skills" line); false negatives
mean the user has to register manually. Bias detection toward
recognising the common shapes.
"""

from __future__ import annotations

from pathlib import Path

from code_scalpel.skills.base import Skill

_POSTGRES_URL_TOKENS = ("postgres://", "postgresql://")
_COMPOSE_FILES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")
_MIGRATIONS_DIRS = ("migrations", "db/migrations")


class PostgresSkill(Skill):
    name = "postgres"
    description = (
        "Postgres component (detects alembic.ini / docker-compose with postgres / "
        ".env DATABASE_URL / SQL migrations)."
    )
    provides_test_runner = False

    def detect(self, root: Path) -> bool:
        if (root / "alembic.ini").is_file():
            return True
        for compose in _COMPOSE_FILES:
            path = root / compose
            if path.is_file():
                try:
                    if "postgres" in path.read_text().lower():
                        return True
                except OSError:
                    pass
        env = root / ".env"
        if env.is_file():
            try:
                text = env.read_text()
                if any(tok in text for tok in _POSTGRES_URL_TOKENS):
                    return True
            except OSError:
                pass
        for migrations in _MIGRATIONS_DIRS:
            mig_dir = root / migrations
            if mig_dir.is_dir() and any(mig_dir.glob("*.sql")):
                return True
        return False

    def test_cmd(self, args: str = "") -> list[str]:
        # Component-only: no standalone test command. Returned empty so
        # the registry's `default_runnable` filter ignores this skill in
        # the test path. `/skills` still surfaces it.
        return []

    def lint_cmd(self) -> list[str]:
        return []
