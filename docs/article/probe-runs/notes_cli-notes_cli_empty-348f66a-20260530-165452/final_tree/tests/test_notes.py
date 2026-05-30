import pytest
from notes.storage import add_note, list_notes, search_notes, delete_note

def test_add_note():
    add_note("Моя первая заметка")
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == "Моя первая заметка"

def test_list_notes():
    add_note("Заметка 1")
    add_note("Заметка 2")
    notes = list_notes()
    assert len(notes) == 2
    assert notes[0] == "Заметка 1"
    assert notes[1] == "Заметка 2"

def test_search_notes():
    add_note("Заметка с ключевым словом")
    notes = search_notes("ключевое")
    assert len(notes) == 1
    assert notes[0] == "Заметка с ключевым словом"

def test_delete_note():
    add_note("Заметка для удаления")
    delete_note(0)
    notes = list_notes()
    assert len(notes) == 0