import pytest
from storage import NoteStorage

def setup_module(module):
    module.storage = NoteStorage()
    module.storage.notes = []

def test_add():
    storage = NoteStorage()
    storage.add('Заметка 1')
    assert len(storage.list()) == 1
    assert storage.list()[0] == 'Заметка 1'

def test_list():
    storage = NoteStorage()
    storage.add('Заметка 1')
    storage.add('Заметка 2')
    notes = storage.list()
    assert len(notes) == 2
    assert 'Заметка 1' in notes
    assert 'Заметка 2' in notes

def test_search():
    storage = NoteStorage()
    storage.add('Заметка 1')
    storage.add('Заметка 2')
    results = storage.search('Заметка')
    assert len(results) == 2
    assert 'Заметка 1' in results
    assert 'Заметка 2' in results

def test_delete():
    storage = NoteStorage()
    storage.add('Заметка 1')
    storage.add('Заметка 2')
    storage.delete(0)
    notes = storage.list()
    assert len(notes) == 1
    assert 'Заметка 2' in notes