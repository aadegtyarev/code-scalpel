"""SqliteSkill — component skill marking that the project uses SQLite.

Like PostgresSkill, SQLite is detected and surfaced in `/skills` but
doesn't own a test runner (`provides_test_runner = False`). The
language skill keeps running tests; SQLite presence is a context hint
for the agent (relevant when discussing migrations, schema queries,
or `.db` file management).

Detection: any tracked `*.db` / `*.sqlite` / `*.sqlite3` file at the
top level or under `db/`, OR a `schema.sql` at the top level. We
deliberately skip `.cache/` and other gitignored areas — those would
catch unrelated tool databases (pytest cache, mypy cache).
"""

from __future__ import annotations

from pathlib import Path

from code_scalpel.skills.base import Skill

_DB_EXTENSIONS = (".db", ".sqlite", ".sqlite3")
_DB_DIRS = (".", "db")


class SqliteSkill(Skill):
    name = "sqlite"
    description = "SQLite component (detects *.db / *.sqlite files or top-level schema.sql)."
    provides_test_runner = False

    def detect(self, root: Path) -> bool:
        if (root / "schema.sql").is_file():
            return True
        for sub in _DB_DIRS:
            search = root if sub == "." else (root / sub)
            if not search.is_dir():
                continue
            for entry in search.iterdir():
                if entry.is_file() and entry.suffix.lower() in _DB_EXTENSIONS:
                    return True
        return False

    def test_cmd(self, args: str = "") -> list[str]:
        return []

    def lint_cmd(self) -> list[str]:
        return []
