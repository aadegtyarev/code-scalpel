from notes_cli.models import Note
from notes_cli.service import NotesService


class MemoryStorage:
    def __init__(self, notes: list[Note] | None = None):
        self.notes = list(notes or [])
        self.saved: list[Note] | None = None

    def load(self) -> list[Note]:
        return list(self.notes)

    def save(self, notes: list[Note]) -> None:
        self.saved = list(notes)
        self.notes = list(notes)


def test_add_creates_note_and_saves_it():
    storage = MemoryStorage()
    service = NotesService(storage)

    note = service.add("Idea", "Write tests")

    assert note.title == "Idea"
    assert note.text == "Write tests"
    assert note.id
    assert note.created_at
    assert storage.saved == [note]


def test_list_returns_notes_in_storage_order():
    notes = [
        Note(id="1", title="First", text="One", created_at="2026-05-31T12:00:00Z"),
        Note(id="2", title="Second", text="Two", created_at="2026-05-31T12:01:00Z"),
    ]
    service = NotesService(MemoryStorage(notes))

    assert service.list() == notes


def test_search_matches_title_and_text_case_insensitively():
    notes = [
        Note(id="1", title="Shopping", text="Buy Milk", created_at="2026-05-31T12:00:00Z"),
        Note(id="2", title="Work", text="Prepare CLI demo", created_at="2026-05-31T12:01:00Z"),
        Note(id="3", title="Other", text="Nothing relevant", created_at="2026-05-31T12:02:00Z"),
    ]
    service = NotesService(MemoryStorage(notes))

    assert service.search("cli") == [notes[1]]
    assert service.search("milk") == [notes[0]]


def test_delete_removes_note_and_reports_missing_id():
    notes = [
        Note(id="1", title="First", text="One", created_at="2026-05-31T12:00:00Z"),
        Note(id="2", title="Second", text="Two", created_at="2026-05-31T12:01:00Z"),
    ]
    storage = MemoryStorage(notes)
    service = NotesService(storage)

    result = service.delete("1")

    assert result.deleted is True
    assert storage.notes == [notes[1]]
    assert service.delete("missing").deleted is False
