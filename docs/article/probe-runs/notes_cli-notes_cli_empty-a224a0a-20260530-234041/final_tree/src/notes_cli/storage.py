from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

from .models import Note


class NoteStorage:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> list[Note]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [Note.from_dict(item) for item in data]

    def save(self, notes: list[Note]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [note.to_dict() for note in notes]
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, title: str, content: str) -> Note:
        notes = self.load()
        note = Note.create(uuid4().hex, title, content)
        notes.append(note)
        self.save(notes)
        return note

    def search(self, query: str) -> list[Note]:
        return [note for note in self.load() if note.matches(query)]

    def delete(self, note_id: str) -> bool:
        notes = self.load()
        remaining = [note for note in notes if note.id != note_id]
        if len(remaining) == len(notes):
            return False
        self.save(remaining)
        return True
