import os
from notes import add, list_notes, search, delete

def setup_module(module):
    if os.path.exists('notes.json'):
        os.remove('notes.json')

def test_add():
    add('Test note 1')
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == 'Test note 1'

    add('Test note 2')
    notes = list_notes()
    assert len(notes) == 2
    assert notes[1] == 'Test note 2'

def test_list():
    notes = list_notes()
    assert isinstance(notes, list)

    add('Test note 3')
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == 'Test note 3'

def test_search():
    add('Test note 4')
    results = search('test')
    assert len(results) == 1
    assert results[0] == 'Test note 4'

    results = search('nonexistent')
    assert len(results) == 0

def test_delete():
    add('Test note 5')
    notes = list_notes()
    assert len(notes) == 1
    delete(0)
    notes = list_notes()
    assert len(notes) == 0

    add('Test note 6')
    add('Test note 7')
    delete(1)
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == 'Test note 6'
