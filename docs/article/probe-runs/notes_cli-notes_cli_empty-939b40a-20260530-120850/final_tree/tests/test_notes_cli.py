import pytest
from notes_cli.storage import JSONStorage
from notes_cli.note import Note

def setup_module(module):
    # Ensure a clean state before running tests
    storage = JSONStorage('test_notes.json')
    storage.notes = []
    storage.save_notes()

def test_add():
    storage = JSONStorage('test_notes.json')
    note = storage.add('Test note')
    assert isinstance(note, Note)
    assert note.content == 'Test note'


def test_list():
    storage = JSONStorage('test_notes.json')
    storage.add('Note 1')
    storage.add('Note 2')
    notes = storage.get_all()
    assert len(notes) == 2
    assert notes[0].content == 'Note 1'
    assert notes[1].content == 'Note 2'


def test_search():
    storage = JSONStorage('test_notes.json')
    storage.add('Test note')
    results = storage.search('Test')
    assert len(results) == 1
    assert results[0].content == 'Test note'


def test_delete():
    storage = JSONStorage('test_notes.json')
    note = storage.add('Note to delete')
    storage.delete(note.id)
    notes = storage.get_all()
    assert len(notes) == 0