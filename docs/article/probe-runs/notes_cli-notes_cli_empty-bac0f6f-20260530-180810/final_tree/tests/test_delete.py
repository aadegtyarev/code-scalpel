import pytest
from notes import add, list_notes, delete

def test_delete_empty():
    delete(0)
    assert len(list_notes()) == 0

def test_delete_single_note():
    add('Заметка 1')
    delete(0)
    assert len(list_notes()) == 0

def test_delete_multiple_notes():
    add('Заметка 1')
    add('Заметка 2')
    add('Заметка 3')
    delete(1)
    notes = list_notes()
    assert len(notes) == 2
    assert notes[0] == 'Заметка 1'
    assert notes[1] == 'Заметка 3'

def test_delete_out_of_range():
    add('Заметка 1')
    delete(5)
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == 'Заметка 1'

def test_delete_negative_index():
    add('Заметка 1')
    delete(-1)
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == 'Заметка 1'