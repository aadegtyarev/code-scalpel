import pytest
from app import add_note, list_notes, search_notes, delete_note

def test_add_note():
    add_note("Запись первой заметки")
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == "Запись первой заметки"

def test_list_notes():
    add_note("Запись первой заметки")
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == "Запись первой заметки"

def test_search_notes():
    add_note("Запись первой заметки")
    notes = search_notes("заметка")
    assert len(notes) == 1
    assert notes[0] == "Запись первой заметки"

def test_delete_note():
    add_note("Запись первой заметки")
    delete_note(0)
    notes = list_notes()
    assert len(notes) == 0