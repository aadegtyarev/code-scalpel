from notes_cli import NoteStorage


def test_storage_roundtrip_preserves_fields(tmp_path):
    storage = NoteStorage(tmp_path / "notes.json")
    note = storage.add("Title", "Body")

    loaded = storage.load()

    assert len(loaded) == 1
    assert loaded[0].id == note.id
    assert loaded[0].title == "Title"
    assert loaded[0].content == "Body"
    assert loaded[0].created_at == note.created_at


def test_add_creates_unique_id_and_timestamp(tmp_path):
    storage = NoteStorage(tmp_path / "notes.json")

    first = storage.add("One", "Body")
    second = storage.add("Two", "Body")

    assert first.id != second.id
    assert first.created_at
    assert second.created_at


def test_search_matches_title_and_content(tmp_path):
    storage = NoteStorage(tmp_path / "notes.json")
    storage.add("Shopping", "Buy milk")
    storage.add("Work", "Prepare report")

    by_title = storage.search("shop")
    by_content = storage.search("milk")

    assert [note.title for note in by_title] == ["Shopping"]
    assert [note.title for note in by_content] == ["Shopping"]


def test_delete_removes_note_and_reports_missing_id(tmp_path):
    storage = NoteStorage(tmp_path / "notes.json")
    note = storage.add("Shopping", "Buy milk")

    assert storage.delete(note.id) is True
    assert storage.load() == []
    assert storage.delete("missing") is False
