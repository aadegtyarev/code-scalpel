from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Note:
    id: int = 0
    title: str = ""
    body: str = ""


class NotesStorage:
    def __init__(self, path: str = "notes.json") -> None:
        self._path = Path(path)
        self._notes: list[Note] = []
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            with open(self._path) as f:
                data = json.load(f)
            self._notes = [Note(**item) for item in data]
        else:
            self._notes = []

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w") as f:
            json.dump(
                [asdict(n) for n in self._notes],
                f,
                indent=2,
                ensure_ascii=False,
            )

    def _next_id(self) -> int:
        if not self._notes:
            return 1
        return max(n.id for n in self._notes) + 1

    def add(self, note: Note) -> Note:
        note.id = self._next_id()
        self._notes.append(note)
        self._save()
        return note

    def get_all(self) -> list[Note]:
        return list(self._notes)

    def search(self, query: str) -> list[Note]:
        q = query.lower()
        return [n for n in self._notes if q in n.title.lower() or q in n.body.lower()]

    def delete(self, note_id: int) -> None:
        for i, n in enumerate(self._notes):
            if n.id == note_id:
                del self._notes[i]
                self._save()
                return
        raise KeyError(f"Note with id {note_id} not found")
