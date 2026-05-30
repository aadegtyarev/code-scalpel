import pytest
from main import add, search, load_notes

def test_search(capsys):
    note_text1 = "Первая тестовая заметка"
    note_text2 = "Вторая тестовая заметка"
    add(note_text1)
    add(note_text2)
    search("заметка")
    captured = capsys.readouterr()
    assert f"16: {note_text1}" in captured.out
    assert f"17: {note_text2}" in captured.out