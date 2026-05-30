import pytest
import os
from storage import add_note, get_notes, search_notes, delete_note

def reset_storage():
    if os.path.exists('notes.json'):
        os.remove('notes.json')

def test_add_note():
    reset_storage()
    add_note("Тестовая заметка")
    notes = get_notes()
    assert len(notes) == 1
    assert notes[0] == "Тестовая заметка"

def test_get_notes():
    reset_storage()
    add_note("Заметка 1")
    add_note("Заметка 2")
    notes = get_notes()
    assert len(notes) == 2
    assert notes[0] == "Заметка 1"
    assert notes[1] == "Заметка 2"

def test_search_notes():
    reset_storage()
    add_note("Первая заметка")
    add_note("Вторая заметка")
    results = search_notes("Первая")
    assert len(results) == 1
    assert results[0] == "Первая заметка"

def test_delete_note():
    reset_storage()
    add_note("Удаляемая заметка")
    delete_note(0)
    notes = get_notes()
    assert len(notes) == 0