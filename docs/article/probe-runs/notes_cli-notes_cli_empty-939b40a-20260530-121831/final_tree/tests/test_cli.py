import json
import pytest
from notes.cli import add_note, list_notes, search_notes, delete_note

def setup_module():
    with open('notes/notes.json', 'w') as f:
        json.dump([], f)

def test_add_note():
    add_note('Заметка 1')
    with open('notes/notes.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 1
    assert notes[0]['text'] == 'Заметка 1'

def test_list_notes(capsys):
    add_note('Заметка 2')
    list_notes()
    captured = capsys.readouterr()
    assert '1: Заметка 1' in captured.out
    assert '2: Заметка 2' in captured.out

def test_search_notes(capsys):
    add_note('Заметка 3')
    search_notes('заметка')
    captured = capsys.readouterr()
    assert '1: Заметка 1' in captured.out
    assert '2: Заметка 2' in captured.out
    assert '3: Заметка 3' in captured.out

def test_delete_note():
    add_note('Заметка 4')
    delete_note(1)
    with open('notes/notes.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 0