import json
from notes import add, list_notes, load_notes

def test_list(capsys):
    # Arrange
    note_text = "Тестовая заметка"
    add(note_text)
    expected_output = f"1. {note_text}\n"

    # Act
    list_notes()
    captured = capsys.readouterr()

    # Assert
    assert captured.out == expected_output