import pytest
from main import add, list_notes, load_notes

def test_list_notes(capsys):
    note_text1 = "Первая тестовая заметка"
    note_text2 = "Вторая тестовая заметка"
    add(note_text1)
    add(note_text2)
    list_notes()
    captured = capsys.readouterr()
    assert f"6: {note_text1}" in captured.out
    assert f"7: {note_text2}" in captured.out