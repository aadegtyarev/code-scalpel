import pytest
from src.notes import Notes, JsonStorage
def test_add():
    storage = JsonStorage('test_notes.json')
    notes = Notes(storage)
    notes.add('Test note 1')
    assert len(notes.list()) == 1
def test_list():
    storage = JsonStorage('test_notes.json')
    notes = Notes(storage)
    notes.add('Test note 2')
    notes.add('Test note 3')
    assert notes.list() == ['Test note 2', 'Test note 3']
def test_search():
    storage = JsonStorage('test_notes.json')
    notes = Notes(storage)
    notes.add('Test note 4')
    notes.add('Another test note')
    assert notes.search('test') == ['Test note 4', 'Another test note']
def test_delete():
    storage = JsonStorage('test_notes.json')
    notes = Notes(storage)
    notes.add('Test note 5')
    notes.delete(0)
    assert len(notes.list()) == 0