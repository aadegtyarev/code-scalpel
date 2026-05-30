import pytest
from notes.storage import Storage

def test_add():
    storage = Storage()
    note_id = storage.add('Test Note')
    assert note_id == 1
    notes = storage.list()
    assert len(notes) == 1
    assert notes[0]['id'] == 1
    assert notes[0]['text'] == 'Test Note'

def test_list():
    storage = Storage()
    storage.add('Note 1')
    storage.add('Note 2')
    notes = storage.list()
    assert len(notes) == 2
    assert notes[0]['id'] == 1
    assert notes[0]['text'] == 'Note 1'
    assert notes[1]['id'] == 2
    assert notes[1]['text'] == 'Note 2'

def test_search():
    storage = Storage()
    storage.add('Test Note')
    results = storage.search('Test')
    assert len(results) == 1
    assert results[0]['id'] == 1
    assert results[0]['text'] == 'Test Note'
    results = storage.search('Nonexistent')
    assert len(results) == 0

def test_delete():
    storage = Storage()
    note_id = storage.add('Note to Delete')
    storage.delete(note_id)
    notes = storage.list()
    assert len(notes) == 0