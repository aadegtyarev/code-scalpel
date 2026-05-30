import pytest
from notes.cli import add_note, load_notes

def test_add_single_note():
    initial_notes = load_notes()
    add_note('Test note')
    updated_notes = load_notes()
    assert len(updated_notes) == len(initial_notes) + 1
    assert 'Test note' in updated_notes

def test_add_multiple_notes():
    initial_notes = load_notes()
    add_note('Note 1')
    add_note('Note 2')
    updated_notes = load_notes()
    assert len(updated_notes) == len(initial_notes) + 2
    assert 'Note 1' in updated_notes
    assert 'Note 2' in updated_notes