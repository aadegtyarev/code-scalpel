import pytest
import json
from notes.notes import add, list, search, delete

def clear_notes():
    with open('notes.json', 'w') as f:
        json.dump([], f)

def test_add():
    clear_notes()
    add('First note')
    assert len(list()) == 1

def test_list():
    clear_notes()
    add('Second note')
    notes = list()
    assert len(notes) == 1
    assert 'Second note' in [note['note'] for note in notes]

def test_search():
    clear_notes()
    add('Third note')
    results = search('third')
    assert len(results) == 1
    assert 'Third note' in [note['note'] for note in results]

def test_delete():
    clear_notes()
    add('Fourth note')
    notes_before = list()
    delete(notes_before[0]['id'])
    notes_after = list()
    assert len(notes_after) == 0
    assert 'Fourth note' not in [note['note'] for note in notes_after]