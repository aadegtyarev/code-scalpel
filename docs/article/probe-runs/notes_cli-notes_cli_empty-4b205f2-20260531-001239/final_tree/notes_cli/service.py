from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

from notes_cli.models import Note
from notes_cli.storage import JsonNoteStorage


@dataclass(slots=True)
class DeleteResult:
    deleted: bool


class NotesService:
    def __init__(self, storage: JsonNoteStorage):
        self.storage = storage

    def add(self, title: str, text: str) -> Note:
        note = Note(
            id=uuid4().hex,
            title=title,
            text=text,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        notes = self.storage.load()
        notes.append(note)
        self.storage.save(notes)
        return note

    def list(self) -> list[Note]:
        return self.storage.load()

    def search(self, query: str) -> list[Note]:
        needle = query.casefold()
        return [
            note
            for note in self.storage.load()
            if needle in note.title.casefold() or needle in note.text.casefold()
        ]

    def delete(self, note_id: str) -> DeleteResult:
        notes = self.storage.load()
        remaining = [note for note in notes if note.id != note_id]
        deleted = len(remaining) != len(notes)
        if deleted:
            self.storage.save(remaining)
        return DeleteResult(deleted=deleted)
