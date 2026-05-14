import pytest
import json
from notes.storage import add_note, list_notes, delete_note

def clear_notes():
    with open('notes.json', 'w') as f:
        json.dump([], f)

@pytest.fixture(autouse=True)
def setup_teardown():
    clear_notes()
    yield
    clear_notes()

def test_add_note():
    initial_notes = list_notes()
    note_to_add = 'Test Note'
    add_note(note_to_add)
    updated_notes = list_notes()
    assert len(updated_notes) == len(initial_notes) + 1
    assert note_to_add in updated_notes

def test_list_notes():
    notes_to_add = ['Note 1', 'Note 2', 'Note 3']
    for note in notes_to_add:
        add_note(note)
    listed_notes = list_notes()
    assert len(listed_notes) == len(notes_to_add)
    for note in notes_to_add:
        assert note in listed_notes