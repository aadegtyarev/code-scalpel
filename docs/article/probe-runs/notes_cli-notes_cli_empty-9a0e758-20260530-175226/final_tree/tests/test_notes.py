import pytest
import json
from src.notes.notes import add_note, list_notes, search_notes, delete_note
def clear_notes():
    with open('notes.json', 'w') as file:
        json.dump([], file)

def test_add_note():
    clear_notes()
    add_note('Заметка 1')
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == 'Заметка 1'

def test_list_notes():
    clear_notes()
    add_note('Заметка 2')
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == 'Заметка 2'

def test_search_notes():
    clear_notes()
    add_note('Заметка 3')
    result = search_notes('заметка')
    assert len(result) == 1
    assert result[0] == 'Заметка 3'

def test_delete_note():
    clear_notes()
    add_note('Заметка 4')
    delete_note(0)
    notes = list_notes()
    assert len(notes) == 0