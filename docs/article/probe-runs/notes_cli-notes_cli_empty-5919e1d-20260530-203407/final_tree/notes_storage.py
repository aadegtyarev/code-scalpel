from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


@dataclass(slots=True)
class Note:
    id: int
    text: str
    created_at: str


class NoteStore:
    def __init__(self, path: str | Path = "notes.json") -> None:
        self.path = Path(path)

    def _read(self) -> list[Note]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [Note(**item) for item in data]

    def _write(self, notes: Iterable[Note]) -> None:
        self.path.write_text(
            json.dumps([asdict(note) for note in notes], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def add(self, text: str) -> Note:
        notes = self._read()
        next_id = max((note.id for note in notes), default=0) + 1
        note = Note(
            id=next_id,
            text=text,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        notes.append(note)
        self._write(notes)
        return note

    def list(self) -> list[Note]:
        return self._read()

    def search(self, query: str) -> list[Note]:
        query_lower = query.lower()
        return [note for note in self._read() if query_lower in note.text.lower()]

    def delete(self, note_id: int) -> bool:
        notes = self._read()
        remaining = [note for note in notes if note.id != note_id]
        if len(remaining) == len(notes):
            return False
        self._write(remaining)
        return True
