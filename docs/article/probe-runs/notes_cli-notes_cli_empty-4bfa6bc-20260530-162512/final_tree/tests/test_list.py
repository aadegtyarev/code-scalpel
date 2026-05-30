import pytest
from notes.cli import list_notes, load_notes

def test_list_no_notes(capsys):
    with open('notes.json', 'w') as f:
        json.dump({}, f)
    list_notes()
    captured = capsys.readouterr()
    assert captured.out == "Нет заметок\n"

def test_list_with_notes(capsys):
    notes = {
        '1': 'Первая заметка',
        '2': 'Вторая заметка'
    }
    with open('notes.json', 'w') as f:
        json.dump(notes, f)
    list_notes()
    captured = capsys.readouterr()
    assert captured.out == "1: Первая заметка\n2: Вторая заметка\n"