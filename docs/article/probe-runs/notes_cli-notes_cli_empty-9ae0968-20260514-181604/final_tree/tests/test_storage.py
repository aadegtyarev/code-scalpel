import pytest
from notes_app.storage import NotesStorage

def test_add(storage):
    storage.add('Test note')
    assert len(storage.notes) == 1
    assert storage.notes[0] == 'Test note'

def test_list(storage):
    storage.add('Note 1')
    storage.add('Note 2')
    notes = storage.list()
    assert notes == ['Note 1', 'Note 2']

def test_search(storage):
    storage.add('Test note')
    results = storage.search('test')
    assert results == ['Test note']

def test_delete(storage):
    storage.add('Note 1')
    storage.delete(0)
    notes = storage.list()
    assert notes == []

@pytest.fixture
def storage():
    storage = NotesStorage(filepath='tests/test_notes.json')
    storage.notes = []  # Reset the storage before each test
    return storage