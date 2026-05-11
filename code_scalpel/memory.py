"""Persistent project memory — sqlite-backed, with full-text search.

This is the thin own-implementation that replaces a dependency on
mem0ai (skipped per the spike on 2026-05-11). Scope is intentionally
narrow: two methods (`add` / `search`), one storage backend
(sqlite + FTS5, no new dependencies, deterministic ranking), and a
single domain concept (`MemoryEntry`).

What this is for:
- Persist user preferences and project facts across sessions
  ("user wants ты, не вы", "tests run via `pytest -x`",
  "compact lives in StepAgent, not Session"). The agent can recall
  them in future sessions without /new wiping everything.
- Surface relevant snippets when the user asks something the model
  has been told before.

What this is NOT:
- Semantic retrieval (no embeddings yet — FTS5 BM25 is enough for
  the first pass; vectors land when we hit BM25 ceiling).
- Multi-user / multi-tenant. One project, one .code-scalpel/memory.db.
- Dedupe of contradictions. The model can produce one when it asks
  for recall and gets two conflicting entries — that's fine for now,
  and easier to spot than to silently merge.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

_DEFAULT_DB = Path(".code-scalpel") / "memory.db"

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS memory (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL DEFAULT 'fact',
    text        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    source      TEXT
);
CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts
USING fts5(text, content='memory', content_rowid='id', tokenize='unicode61');
CREATE TRIGGER IF NOT EXISTS memory_ai AFTER INSERT ON memory BEGIN
    INSERT INTO memory_fts(rowid, text) VALUES (new.id, new.text);
END;
CREATE TRIGGER IF NOT EXISTS memory_ad AFTER DELETE ON memory BEGIN
    INSERT INTO memory_fts(memory_fts, rowid, text) VALUES('delete', old.id, old.text);
END;
"""


@dataclass(frozen=True)
class MemoryEntry:
    id: int
    kind: str
    text: str
    created_at: datetime
    source: str | None


class MemoryStore:
    """sqlite-backed fact store with FTS5 retrieval. Thread-unsafe by
    design (the TUI runs single-threaded async); reuse one instance per
    session. Database file lives in `.code-scalpel/memory.db` by default."""

    def __init__(self, root: Path | None = None, db_path: Path | None = None) -> None:
        if db_path is None:
            db_path = (root or Path(".")) / _DEFAULT_DB
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self._db_path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def add(self, text: str, *, kind: str = "fact", source: str | None = None) -> int:
        """Persist a memory entry. Returns the new row id.

        Empty / whitespace text is rejected — refuse to clutter the store
        with no-op rows. Callers can use this to test storage before
        committing to a value."""
        cleaned = text.strip()
        if not cleaned:
            raise ValueError("memory text must be non-empty")
        now = datetime.now(UTC).isoformat()
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO memory (kind, text, created_at, source) VALUES (?, ?, ?, ?)",
                (kind, cleaned, now, source),
            )
            return int(cur.lastrowid or 0)

    def search(self, query: str, *, k: int = 5) -> list[MemoryEntry]:
        """Return up to `k` entries ranked by FTS5 BM25 against the query.

        Query is treated as a free-text phrase — FTS5 handles tokenisation.
        If the query has no useful tokens (e.g. only punctuation) FTS5
        raises; we catch and return an empty list rather than letting it
        propagate, because empty result is the right semantic answer."""
        cleaned = query.strip()
        if not cleaned:
            return []
        sql = (
            "SELECT m.id, m.kind, m.text, m.created_at, m.source "
            "FROM memory_fts f JOIN memory m ON f.rowid = m.id "
            "WHERE memory_fts MATCH ? ORDER BY rank LIMIT ?"
        )
        with self._conn() as conn:
            try:
                rows = conn.execute(sql, (cleaned, k)).fetchall()
            except sqlite3.OperationalError:
                # Malformed FTS5 query (e.g. user typed `"`, `*`, only
                # punctuation). Return nothing; the caller can recover.
                return []
        return [
            MemoryEntry(
                id=int(row[0]),
                kind=str(row[1]),
                text=str(row[2]),
                created_at=datetime.fromisoformat(str(row[3])),
                source=row[4],
            )
            for row in rows
        ]

    def all(self) -> list[MemoryEntry]:
        """All entries, newest first. Useful for /memory listing UX."""
        sql = "SELECT id, kind, text, created_at, source FROM memory ORDER BY id DESC"
        with self._conn() as conn:
            rows = conn.execute(sql).fetchall()
        return [
            MemoryEntry(
                id=int(row[0]),
                kind=str(row[1]),
                text=str(row[2]),
                created_at=datetime.fromisoformat(str(row[3])),
                source=row[4],
            )
            for row in rows
        ]

    def delete(self, entry_id: int) -> bool:
        """Remove one entry by id. Returns True if a row was deleted."""
        with self._conn() as conn:
            cur = conn.execute("DELETE FROM memory WHERE id = ?", (entry_id,))
            return cur.rowcount > 0

    def clear(self) -> None:
        """Remove all entries. Used by /forget-all and tests."""
        with self._conn() as conn:
            conn.execute("DELETE FROM memory")

    def __len__(self) -> int:
        with self._conn() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM memory").fetchone()[0])
