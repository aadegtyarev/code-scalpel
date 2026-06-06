from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable
from uuid import uuid4

from notes_cli.models import Note


class NoteNotFoundError(LookupError):
    pass


class NoteStore:
    def __init__(self, path: Path):
        self.path = path

    def load(self) -> list[Note]:
        if not self.path.exists():
            return []
        data = json.loads(self.path.read_text(encoding="utf-8"))
        return [Note.from_dict(item) for item in data]

    def save(self, notes: Iterable[Note]) -> None:
        payload = [note.to_dict() for note in notes]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def add(self, title: str, body: str = "") -> Note:
        notes = self.load()
        note = Note.create(uuid4().hex, title=title, body=body)
        notes.append(note)
        self.save(notes)
        return note

    def list(self) -> list[Note]:
        return self.load()

    def search(self, query: str) -> list[Note]:
        query_lower = query.lower()
        return [
            note
            for note in self.load()
            if query_lower in note.title.lower() or query_lower in note.body.lower()
        ]

    def delete(self, note_id: str) -> Note:
        notes = self.load()
        for index, note in enumerate(notes):
            if note.id == note_id:
                removed = notes.pop(index)
                self.save(notes)
                return removed
        raise NoteNotFoundError(note_id)
