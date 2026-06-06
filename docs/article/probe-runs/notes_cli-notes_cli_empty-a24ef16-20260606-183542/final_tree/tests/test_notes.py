import pytest
from notes import main, add_note, search_notes, delete_note, load_notes

def test_add_note():
    add_note('Первая заметка')
    notes = load_notes()
    assert len(notes) == 1
    assert notes[0]['text'] == 'Первая заметка'


def test_list_notes(capsys):
    add_note('Вторая заметка')
    main(['notes.py', 'list'])
    captured = capsys.readouterr()
    assert '2: Вторая заметка' in captured.out


def test_search_notes():
    add_note('Третья заметка')
    notes = search_notes('третья')
    assert len(notes) == 1
    assert notes[0]['text'] == 'Третья заметка'


def test_delete_note():
    add_note('Четвертая заметка')
    delete_note(1)
    notes = load_notes()
    assert len(notes) == 0