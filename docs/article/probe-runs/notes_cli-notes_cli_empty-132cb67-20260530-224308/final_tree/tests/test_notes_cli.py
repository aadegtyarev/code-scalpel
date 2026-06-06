from pathlib import Path

from notes_cli import add_note, delete_note, list_notes, search_notes


def test_add_and_list_notes(tmp_path: Path) -> None:
    storage = tmp_path / "notes.json"

    note = add_note(storage, "Купить молоко")

    assert note.id == 1
    assert note.text == "Купить молоко"
    assert storage.exists()
    assert list_notes(storage) == [note]


def test_search_notes(tmp_path: Path) -> None:
    storage = tmp_path / "notes.json"
    add_note(storage, "Купить молоко")
    add_note(storage, "Позвонить врачу")

    matches = search_notes(storage, "молоко")

    assert [note.text for note in matches] == ["Купить молоко"]


def test_delete_note(tmp_path: Path) -> None:
    storage = tmp_path / "notes.json"
    first = add_note(storage, "Купить молоко")
    second = add_note(storage, "Позвонить врачу")

    assert delete_note(storage, first.id) is True
    assert [note.text for note in list_notes(storage)] == [second.text]
    assert delete_note(storage, 999) is False
