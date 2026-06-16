from __future__ import annotations

import json

import pytest

from notes.storage import Note, NotesStorage


class TestNotesStorage:
    def test_add_assigns_id(self, tmp_path: pytest.TempPathFactory) -> None:
        store = NotesStorage(str(tmp_path / "notes.json"))
        note = store.add(Note(title="t", body="b"))
        assert note.id == 1

    def test_add_second_gets_incremented_id(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        store = NotesStorage(str(tmp_path / "notes.json"))
        store.add(Note(title="a", body="b"))
        note2 = store.add(Note(title="c", body="d"))
        assert note2.id == 2

    def test_add_persists_to_file(self, tmp_path: pytest.TempPathFactory) -> None:
        p = tmp_path / "notes.json"
        store = NotesStorage(str(p))
        store.add(Note(title="t", body="b"))
        data = json.loads(p.read_text())
        assert data == [{"id": 1, "title": "t", "body": "b"}]

    def test_get_all_empty(self, tmp_path: pytest.TempPathFactory) -> None:
        store = NotesStorage(str(tmp_path / "notes.json"))
        assert store.get_all() == []

    def test_get_all_returns_all(self, tmp_path: pytest.TempPathFactory) -> None:
        store = NotesStorage(str(tmp_path / "notes.json"))
        n1 = store.add(Note(title="a", body="b"))
        n2 = store.add(Note(title="c", body="d"))
        assert store.get_all() == [n1, n2]

    def test_load_existing_data(self, tmp_path: pytest.TempPathFactory) -> None:
        p = tmp_path / "notes.json"
        p.write_text('[{"id": 1, "title": "t", "body": "b"}]')
        store = NotesStorage(str(p))
        notes = store.get_all()
        assert len(notes) == 1
        assert notes[0].id == 1
        assert notes[0].title == "t"
        assert notes[0].body == "b"

    @pytest.mark.parametrize(
        "query,expected_ids",
        [
            ("hello", [1]),
            ("world", [1]),
            ("HELLO", [1]),
            ("foo", [2]),
            ("bar", [2]),
            ("miss", []),
            ("abc", []),
        ],
    )
    def test_search(
        self,
        tmp_path: pytest.TempPathFactory,
        query: str,
        expected_ids: list[int],
    ) -> None:
        store = NotesStorage(str(tmp_path / "notes.json"))
        store.add(Note(title="Hello", body="world"))
        store.add(Note(title="Foo", body="bar"))
        results = store.search(query)
        assert [n.id for n in results] == expected_ids

    def test_search_matches_body(self, tmp_path: pytest.TempPathFactory) -> None:
        store = NotesStorage(str(tmp_path / "notes.json"))
        store.add(Note(title="Alpha", body="Beta Gamma"))
        results = store.search("gamma")
        assert len(results) == 1
        assert results[0].title == "Alpha"

    def test_delete_removes_and_saves(self, tmp_path: pytest.TempPathFactory) -> None:
        store = NotesStorage(str(tmp_path / "notes.json"))
        note = store.add(Note(title="t", body="b"))
        store.delete(note.id)
        assert store.get_all() == []

    def test_delete_nonexistent_raises(self, tmp_path: pytest.TempPathFactory) -> None:
        store = NotesStorage(str(tmp_path / "notes.json"))
        with pytest.raises(KeyError):
            store.delete(999)

    def test_delete_only_one(self, tmp_path: pytest.TempPathFactory) -> None:
        store = NotesStorage(str(tmp_path / "notes.json"))
        n1 = store.add(Note(title="a", body="b"))
        n2 = store.add(Note(title="c", body="d"))
        store.delete(n1.id)
        assert store.get_all() == [n2]
