from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
import json


@dataclass(frozen=True, slots=True)
class Note:
    id: int
    text: str
    created_at: str


class NotesStore:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def _read(self) -> list[Note]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [Note(**item) for item in data]

    def _write(self, notes: list[Note]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [asdict(note) for note in notes]
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def add(self, text: str) -> Note:
        notes = self._read()
        next_id = max((note.id for note in notes), default=0) + 1
        note = Note(id=next_id, text=text, created_at=datetime.now(timezone.utc).isoformat())
        notes.append(note)
        self._write(notes)
        return note

    def list(self) -> list[Note]:
        return sorted(self._read(), key=lambda note: note.id)

    def search(self, query: str) -> list[Note]:
        query_lower = query.lower()
        return [note for note in self.list() if query_lower in note.text.lower()]

    def delete(self, note_id: int) -> bool:
        notes = self._read()
        remaining = [note for note in notes if note.id != note_id]
        if len(remaining) == len(notes):
            return False
        self._write(remaining)
        return True
