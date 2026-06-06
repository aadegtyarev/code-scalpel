import json
import os
from pathlib import Path
from typing import List, Optional

from notes_cli.models import Note


class Storage:
    def __init__(self, path: str = "notes.json"):
        self.path = Path(path)

    def load(self) -> List[Note]:
        if not self.path.exists():
            return []
        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [Note.from_dict(item) for item in data]

    def save(self, notes: List[Note]) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump([n.to_dict() for n in notes], f, ensure_ascii=False, indent=2)

    def add(self, note: Note) -> Note:
        notes = self.load()
        if notes:
            note.id = max(n.id for n in notes) + 1
        else:
            note.id = 1
        notes.append(note)
        self.save(notes)
        return note

    def delete(self, note_id: int) -> bool:
        notes = self.load()
        before = len(notes)
        notes = [n for n in notes if n.id != note_id]
        if len(notes) == before:
            return False
        self.save(notes)
        return True

    def search(self, query: str) -> List[Note]:
        notes = self.load()
        q = query.lower()
        return [n for n in notes if q in n.title.lower() or q in n.content.lower()]
