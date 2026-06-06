from pathlib import Path

import pytest

from notes_cli.models import Note
from notes_cli.storage import Storage


class TestNote:
    def test_to_dict(self):
        note = Note(id=1, title="Test", content="Content", created_at="2024-01-01T00:00:00")
        d = note.to_dict()
        assert d["id"] == 1
        assert d["title"] == "Test"
        assert d["content"] == "Content"
        assert d["created_at"] == "2024-01-01T00:00:00"

    def test_from_dict(self):
        data = {"id": 2, "title": "T", "content": "C", "created_at": "2024-06-01T12:00:00"}
        note = Note.from_dict(data)
        assert note.id == 2
        assert note.title == "T"
        assert note.content == "C"
        assert note.created_at == "2024-06-01T12:00:00"

    def test_from_dict_ignores_extra_fields(self):
        data = {"id": 3, "title": "T", "content": "C", "created_at": "2024-01-01T00:00:00", "extra": "x"}
        note = Note.from_dict(data)
        assert note.id == 3
        assert not hasattr(note, "extra")


@pytest.fixture
def storage_path(tmp_path: Path) -> Path:
    return tmp_path / "notes.json"


@pytest.fixture
def storage(storage_path: Path) -> Storage:
    return Storage(str(storage_path))


class TestStorage:
    def test_load_empty_file(self, storage: Storage):
        assert storage.load() == []

    def test_load_nonexistent_file(self, storage: Storage):
        assert storage.load() == []

    def test_save_and_load(self, storage: Storage):
        note = Note(id=1, title="T", content="C", created_at="2024-01-01T00:00:00")
        storage.save([note])
        loaded = storage.load()
        assert len(loaded) == 1
        assert loaded[0].id == 1
        assert loaded[0].title == "T"

    def test_add_increments_id(self, storage: Storage):
        n1 = storage.add(Note(title="A", content="1"))
        n2 = storage.add(Note(title="B", content="2"))
        assert n1.id == 1
        assert n2.id == 2

    def test_add_first_note_id_is_one(self, storage: Storage):
        n = storage.add(Note(title="First", content="x"))
        assert n.id == 1

    def test_delete_existing(self, storage: Storage):
        n = storage.add(Note(title="Del", content="x"))
        assert storage.delete(n.id) is True
        assert storage.load() == []

    def test_delete_nonexisting(self, storage: Storage):
        assert storage.delete(999) is False

    def test_search_by_title(self, storage: Storage):
        storage.add(Note(title="Python", content="lang"))
        storage.add(Note(title="Java", content="lang"))
        results = storage.search("Python")
        assert len(results) == 1
        assert results[0].title == "Python"

    def test_search_by_content(self, storage: Storage):
        storage.add(Note(title="A", content="python"))
        storage.add(Note(title="B", content="java"))
        results = storage.search("python")
        assert len(results) == 1
        assert results[0].title == "A"

    def test_search_case_insensitive(self, storage: Storage):
        storage.add(Note(title="Hello", content="World"))
        results = storage.search("HELLO")
        assert len(results) == 1

    def test_search_no_match(self, storage: Storage):
        storage.add(Note(title="A", content="B"))
        results = storage.search("ZZZ")
        assert results == []

    def test_persists_across_instances(self, storage_path: Path):
        s1 = Storage(str(storage_path))
        s1.add(Note(title="Persist", content="data"))
        s2 = Storage(str(storage_path))
        assert len(s2.load()) == 1
        assert s2.load()[0].title == "Persist"
