import pytest
from src.storage import Storage

def test_add_note():
    storage = Storage()
    storage.add_note('Test note')
    notes = storage.list_notes()
    assert len(notes) == 1
    assert notes[0] == 'Test note'

def test_list_notes():
    storage = Storage()
    storage.add_note('Note 1')
    storage.add_note('Note 2')
    notes = storage.list_notes()
    assert len(notes) == 2
    assert notes[0] == 'Note 1'
    assert notes[1] == 'Note 2'

def test_search_notes():
    storage = Storage()
    storage.add_note('Test note')
    storage.add_note('Another note')
    notes = storage.search_notes('test')
    assert len(notes) == 1
    assert notes[0] == 'Test note'

def test_delete_note():
    storage = Storage()
    storage.add_note('Note to delete')
    index = 0
    storage.delete_note(index)
    notes = storage.list_notes()
    assert len(notes) == 0