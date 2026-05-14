import pytest
from notes_storage import load_notes, save_notes
from notes_cli import add_note, list_notes, search_notes, delete_note

def setup_module():
    save_notes([])

def test_add_note():
    add_note('Test note')
    notes = load_notes()
    assert len(notes) == 1
    assert notes[0]['note'] == 'Test note'

def test_list_notes():
    add_note('First note')
    add_note('Second note')
    list_notes()
    notes = load_notes()
    assert len(notes) == 2
    assert notes[0]['note'] == 'First note'
    assert notes[1]['note'] == 'Second note'

def test_search_notes():
    add_note('Test search')
    search_notes('search')
    notes = load_notes()
    assert len(notes) == 1
    assert notes[0]['note'] == 'Test search'

def test_delete_note():
    add_note('Note to delete')
    notes = load_notes()
    note_id = notes[0]['id']
    delete_note(note_id)
    notes = load_notes()
    assert len(notes) == 0