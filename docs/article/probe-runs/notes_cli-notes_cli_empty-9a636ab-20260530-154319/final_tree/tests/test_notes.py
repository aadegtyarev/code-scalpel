import pytest
from notes.cli import add_note, list_notes, search_notes, delete_note


def test_add_note():
    add_note("Test Note")
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == "Test Note"


def test_list_notes():
    add_note("First Note")
    add_note("Second Note")
    notes = list_notes()
    assert len(notes) == 2
    assert notes[0] == "First Note"
    assert notes[1] == "Second Note"


def test_search_notes():
    add_note("Test Note")
    results = search_notes("Test")
    assert len(results) == 1
    assert results[0] == "Test Note"


def test_delete_note():
    add_note("ToDelete Note")
    delete_note(0)
    notes = list_notes()
    assert len(notes) == 0