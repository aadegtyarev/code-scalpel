"""Тесты для NoteStorage."""

import json
from pathlib import Path

import pytest

from notes_cli.storage import NoteStorage


@pytest.fixture
def storage(tmp_path: Path) -> NoteStorage:
    """Создаёт NoteStorage с временным файлом данных."""
    data_file = tmp_path / "notes.json"
    return NoteStorage(path=data_file)


def test_add(storage: NoteStorage, tmp_path: Path) -> None:
    note_id = storage.add("Hello")
    assert note_id == 1

    note_id = storage.add("World")
    assert note_id == 2

    data = json.loads((tmp_path / "notes.json").read_text())
    assert len(data["notes"]) == 2
    assert data["next_id"] == 3


def test_list_all_empty(storage: NoteStorage) -> None:
    assert storage.list_all() == []


def test_list_all(storage: NoteStorage) -> None:
    storage.add("first")
    storage.add("second")
    notes = storage.list_all()
    assert len(notes) == 2
    assert notes[0]["text"] == "first"
    assert notes[1]["text"] == "second"


def test_search(storage: NoteStorage) -> None:
    storage.add("Python is great")
    storage.add("Java is also good")
    results = storage.search("great")
    assert len(results) == 1
    assert results[0]["text"] == "Python is great"


def test_search_case_insensitive(storage: NoteStorage) -> None:
    storage.add("Hello World")
    results = storage.search("HELLO")
    assert len(results) == 1


def test_search_no_match(storage: NoteStorage) -> None:
    storage.add("Hello")
    assert storage.search("xyz") == []


def test_delete_existing(storage: NoteStorage) -> None:
    nid = storage.add("to delete")
    assert storage.delete(nid) is True
    assert storage.list_all() == []


def test_delete_nonexistent(storage: NoteStorage) -> None:
    assert storage.delete(999) is False


def test_delete_preserves_others(storage: NoteStorage) -> None:
    id1 = storage.add("keep me")
    storage.add("delete me")
    storage.delete(id1 + 1)
    assert len(storage.list_all()) == 1
    assert storage.list_all()[0]["id"] == id1


def test_load_from_missing_file(storage: NoteStorage) -> None:
    """При отсутствии файла данные должны быть пустыми."""
    assert storage.list_all() == []
    assert storage.add("test") == 1
