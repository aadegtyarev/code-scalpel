import json
from datetime import datetime
from pathlib import Path

FILE_PATH = "notes.json"


def _read_notes(path: str | None = None) -> list[dict]:
    filepath = Path(path or FILE_PATH)
    if not filepath.exists():
        return []
    with filepath.open("r", encoding="utf-8") as f:
        return json.load(f)


def _write_notes(notes: list[dict], path: str | None = None) -> None:
    filepath = Path(path or FILE_PATH)
    with filepath.open("w", encoding="utf-8") as f:
        json.dump(notes, f, ensure_ascii=False, indent=2)


def add_note(title: str, body: str, path: str | None = None) -> dict:
    notes = _read_notes(path)
    next_id = max((n["id"] for n in notes), default=0) + 1
    note = {
        "id": next_id,
        "title": title,
        "body": body,
        "created_at": datetime.now().isoformat(),
    }
    notes.append(note)
    _write_notes(notes, path)
    return note


def list_notes(path: str | None = None) -> list[dict]:
    return _read_notes(path)


def search_notes(query: str, path: str | None = None) -> list[dict]:
    notes = _read_notes(path)
    q = query.lower()
    return [
        n
        for n in notes
        if q in n["title"].lower() or q in n["body"].lower()
    ]


def delete_note(note_id: int, path: str | None = None) -> bool:
    notes = _read_notes(path)
    for i, n in enumerate(notes):
        if n["id"] == note_id:
            del notes[i]
            _write_notes(notes, path)
            return True
    return False
