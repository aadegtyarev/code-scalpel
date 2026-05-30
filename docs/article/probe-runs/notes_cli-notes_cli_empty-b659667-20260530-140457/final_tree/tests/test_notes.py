import pytest
from notes import add, list_notes, search, delete
import os

def setup_teardown():
    if os.path.exists('notes.json'):
        os.remove('notes.json')
    yield
    if os.path.exists('notes.json'):
        os.remove('notes.json')

def test_add(setup_teardown, capsys):
    add("Заметка 1")
    captured = capsys.readouterr()
    assert captured.out.strip() == "Заметка добавлена: Заметка 1"

    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == "Заметка 1"

def test_list(setup_teardown, capsys):
    add("Заметка 1")
    add("Заметка 2")
    notes = list_notes()
    assert len(notes) == 2
    assert notes[0] == "Заметка 1"
    assert notes[1] == "Заметка 2"

def test_search(setup_teardown, capsys):
    add("Заметка 1")
    add("Заметка 2")
    found_notes = search("1")
    assert len(found_notes) == 1
    assert found_notes[0] == "Заметка 1"

def test_delete(setup_teardown, capsys):
    add("Заметка 1")
    delete(1)
    captured = capsys.readouterr()
    assert captured.out.strip() == "Заметка удалена: Заметка 1"

    notes = list_notes()
    assert len(notes) == 0