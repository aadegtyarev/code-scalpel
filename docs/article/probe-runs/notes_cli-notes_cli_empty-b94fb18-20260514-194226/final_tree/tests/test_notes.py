import pytest
from notes import load_notes, save_notes

def test_add_note():
    notes = []
    notes.append('Test note')
    save_notes(notes)
    assert load_notes() == ['Test note']

def test_list_notes():
    notes = ['Note 1', 'Note 2']
    save_notes(notes)
    assert load_notes() == ['Note 1', 'Note 2']

def test_search_notes():
    notes = ['Test note', 'Another note', 'Test another']
    save_notes(notes)
    results = [note for note in load_notes() if 'test' in note.lower()]
    assert results == ['Test note', 'Test another']

def test_delete_note():
    notes = ['Note 1', 'Note 2', 'Note 3']
    save_notes(notes)
    del notes[1]
    save_notes(notes)
    assert load_notes() == ['Note 1', 'Note 3']