"""Tests for notescli.storage — all use isolated tmp_path."""

import json
import pytest
from pathlib import Path

from notescli.storage import add_note, list_notes, search_notes, delete_note


def test_add_note(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    nid = add_note("Title", "Content", p)
    assert isinstance(nid, str) and len(nid) > 0
    data = json.loads(p.read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["id"] == nid
    assert data[0]["title"] == "Title"
    assert data[0]["content"] == "Content"
    assert "created_at" in data[0]


def test_add_note_creates_file(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    assert not p.exists()
    add_note("A", "B", p)
    assert p.exists()


def test_list_empty(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    assert list_notes(p) == []


def test_list_returns_sorted(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    id1 = add_note("First", "a", p)
    id2 = add_note("Second", "b", p)
    notes = list_notes(p)
    assert [n["id"] for n in notes] == [id1, id2]


def test_search_by_title(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    add_note("Python project", "some text", p)
    add_note("Grocery list", "milk, eggs", p)
    results = search_notes("python", p)
    assert len(results) == 1
    assert results[0]["title"] == "Python project"


def test_search_by_content(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    add_note("Shopping", "buy milk today", p)
    results = search_notes("milk", p)
    assert len(results) == 1
    assert results[0]["title"] == "Shopping"


def test_search_case_insensitive(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    add_note("Hello", "World", p)
    results = search_notes("hello", p)
    assert len(results) == 1
    results = search_notes("WORLD", p)
    assert len(results) == 1


def test_search_no_match(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    add_note("Alpha", "Beta", p)
    assert search_notes("Gamma", p) == []


def test_delete_existing(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    nid = add_note("To delete", "text", p)
    assert delete_note(nid, p) is True
    assert list_notes(p) == []


def test_delete_non_existent(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    add_note("Keep me", "text", p)
    assert delete_note("no-such-id", p) is False
    assert len(list_notes(p)) == 1


def test_delete_from_empty(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    assert delete_note("anything", p) is False


def test_missing_file_handled(tmp_path: Path) -> None:
    p = tmp_path / "nonexistent.json"
    assert list_notes(p) == []
    assert search_notes("x", p) == []
    assert delete_note("x", p) is False


def test_malformed_json_raises(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    p.write_text("{{{broken", encoding="utf-8")
    with pytest.raises(RuntimeError, match="повреждён"):
        add_note("X", "Y", p)


def test_not_a_list_raises(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    p.write_text('{"key": "value"}', encoding="utf-8")
    with pytest.raises(RuntimeError, match="не список"):
        add_note("X", "Y", p)


def test_multiple_notes_persist(tmp_path: Path) -> None:
    p = tmp_path / "notes.json"
    ids = [add_note(f"Note {i}", f"content {i}", p) for i in range(3)]
    notes = list_notes(p)
    assert len(notes) == 3
    assert [n["id"] for n in notes] == ids


def test_delete_isolated(tmp_path: Path) -> None:
    """Deleting one note does not affect others."""
    p = tmp_path / "notes.json"
    id1 = add_note("First", "a", p)
    id2 = add_note("Second", "b", p)
    id3 = add_note("Third", "c", p)
    delete_note(id2, p)
    remaining = [n["id"] for n in list_notes(p)]
    assert remaining == [id1, id3]
