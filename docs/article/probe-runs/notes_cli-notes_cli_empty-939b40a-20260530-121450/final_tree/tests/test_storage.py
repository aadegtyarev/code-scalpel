import pytest
from notes.storage import Storage
def setup_module(module):
    storage = Storage()
    storage.notes = []
    storage._save()

def test_add():
    storage = Storage()
    storage.add('Тестовая заметка')
    assert len(storage.notes) == 1
    assert storage.notes[0] == 'Тестовая заметка'

def test_list():
    storage = Storage()
    storage.add('Тестовая заметка')
    notes = storage.list()
    assert notes == ['Тестовая заметка']

def test_search():
    storage = Storage()
    storage.add('Тестовая заметка')
    results = storage.search('заметка')
    assert results == ['Тестовая заметка']

def test_delete():
    storage = Storage()
    storage.add('Тестовая заметка')
    storage.delete(0)
    notes = storage.list()
    assert len(notes) == 0