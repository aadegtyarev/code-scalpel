# tests/test_notes.py
import pytest
from notes import add_note, list_notes, search_notes, delete_note
import json
@pytest.fixture(autouse=True)
def clear_storage():
    with open('storage.json', 'w') as file:
        json.dump([], file)
def test_add_note(clear_storage):
    add_note("Test note 1")
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == "Test note 1"
def test_list_notes(clear_storage):
    add_note("Test note 1")
    add_note("Test note 2")
    notes = list_notes()
    assert len(notes) == 2
    assert notes[0] == "Test note 1"
    assert notes[1] == "Test note 2"
def test_search_notes(clear_storage):
    pass
def test_delete_note(clear_storage):
    pass