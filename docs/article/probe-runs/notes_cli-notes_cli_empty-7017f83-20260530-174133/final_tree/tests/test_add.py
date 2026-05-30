import pytest
from main import add, load_notes

def test_add_note():
    note_text = "Тестовая заметка"
    add(note_text)
    notes = load_notes()
    assert len(notes) == 1
    assert '1' in notes
    assert notes['1'] == note_text

def test_add_multiple_notes():
    note_text1 = "Первая тестовая заметка"
    note_text2 = "Вторая тестовая заметка"
    add(note_text1)
    add(note_text2)
    notes = load_notes()
    assert len(notes) == 2
    assert '1' in notes and '2' in notes
    assert notes['1'] == note_text1
    assert notes['2'] == note_text2