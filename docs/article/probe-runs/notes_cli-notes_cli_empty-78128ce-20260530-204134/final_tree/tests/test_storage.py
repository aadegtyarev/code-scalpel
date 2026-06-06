from notes_cli.storage import NotesStore


def test_add_persists_note(tmp_path):
    store = NotesStore(tmp_path / "notes.json")

    note = store.add("Buy milk")

    assert note.id == 1
    assert note.text == "Buy milk"
    assert note.created_at
    assert (tmp_path / "notes.json").read_text(encoding="utf-8") == (
        '[\n'
        '  {\n'
        '    "id": 1,\n'
        '    "text": "Buy milk",\n'
        '    "created_at": "' + note.created_at + '"\n'
        '  }\n'
        ']\n'
    )


def test_list_returns_notes_in_id_order(tmp_path):
    store = NotesStore(tmp_path / "notes.json")
    store.add("Second")
    store.add("First")

    notes = store.list()

    assert [note.id for note in notes] == [1, 2]
    assert [note.text for note in notes] == ["Second", "First"]


def test_search_filters_by_query(tmp_path):
    store = NotesStore(tmp_path / "notes.json")
    store.add("Buy milk")
    store.add("Read book")

    notes = store.search("milk")

    assert [note.text for note in notes] == ["Buy milk"]


def test_delete_removes_note(tmp_path):
    store = NotesStore(tmp_path / "notes.json")
    store.add("Buy milk")
    store.add("Read book")

    deleted = store.delete(1)

    assert deleted is True
    assert [note.id for note in store.list()] == [2]
    assert store.delete(1) is False
