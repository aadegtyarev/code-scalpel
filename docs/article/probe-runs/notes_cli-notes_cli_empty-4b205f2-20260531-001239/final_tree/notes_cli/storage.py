from __future__ import annotations

import json
from pathlib import Path

from notes_cli.models import Note


class JsonNoteStorage:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> list[Note]:
        if not self.path.exists():
            return []
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return []
        data = json.loads(raw)
        return [Note.from_dict(item) for item in data]

    def save(self, notes: list[Note]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = [note.to_dict() for note in notes]
        self.path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
