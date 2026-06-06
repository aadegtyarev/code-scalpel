from pathlib import Path

from notes_cli.models import Note
from notes_cli.storage import JsonNoteStorage


def test_note_round_trip():
    note = Note(id="1", title="Idea", text="Write tests", created_at="2026-05-31T12:00:00Z")

    restored = Note.from_dict(note.to_dict())

    assert restored == note


def test_load_missing_file_returns_empty_list(tmp_path: Path):
    storage = JsonNoteStorage(tmp_path / "notes.json")

    assert storage.load() == []


def test_load_empty_file_returns_empty_list(tmp_path: Path):
    path = tmp_path / "notes.json"
    path.write_text("", encoding="utf-8")
    storage = JsonNoteStorage(path)

    assert storage.load() == []


def test_save_and_load_notes(tmp_path: Path):
    storage = JsonNoteStorage(tmp_path / "notes.json")
    notes = [
        Note(id="1", title="Idea", text="Write tests", created_at="2026-05-31T12:00:00Z"),
        Note(id="2", title="Todo", text="Ship CLI", created_at="2026-05-31T12:01:00Z"),
    ]

    storage.save(notes)

    assert storage.load() == notes
