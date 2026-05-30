import pytest
from notes import add, list_notes

def test_list_empty():
    notes = list_notes()
    assert len(notes) == 0

def test_list_single_note():
    add('Заметка 1')
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == 'Заметка 1'

def test_list_multiple_notes():
    add('Заметка 2')
    add('Заметка 3')
    notes = list_notes()
    assert len(notes) == 2
    assert notes[0] == 'Заметка 2'
    assert notes[1] == 'Заметка 3'