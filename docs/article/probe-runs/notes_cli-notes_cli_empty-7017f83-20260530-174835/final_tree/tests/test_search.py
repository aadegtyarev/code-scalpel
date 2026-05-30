import json
from notes import add, search, load_notes

def test_search(capsys):
    # Arrange
    note_text = "Тестовая заметка"
    add(note_text)
    expected_output = f"1. {note_text}\n"

    # Act
    search("тест")
    captured = capsys.readouterr()

    # Assert
    assert captured.out == expected_output