import pytest
from notes.storage import Storage
def clear_storage(storage):
    storage._save([])

def test_add_note():
    storage = Storage()
    clear_storage(storage)
    storage.add('Заметка 1')
    assert len(storage.list()) == 1
    assert 'Заметка 1' in storage.list()

def test_list_notes():
    storage = Storage()
    clear_storage(storage)
    storage.add('Заметка 1')
    storage.add('Заметка 2')
    notes = storage.list()
    assert len(notes) == 2
    assert 'Заметка 1' in notes
    assert 'Заметка 2' in notes

def test_search_notes():
    storage = Storage()
    clear_storage(storage)
    storage.add('Заметка 1')
    storage.add('Заметка 2')
    results = storage.search('1')
    assert len(results) == 1
    assert 'Заметка 1' in results
    results = storage.search('3')
    assert len(results) == 0

def test_delete_note():
    storage = Storage()
    clear_storage(storage)
    storage.add('Заметка 1')
    storage.add('Заметка 2')
    storage.delete(0)
    notes = storage.list()
    assert len(notes) == 1
    assert 'Заметка 2' in notes