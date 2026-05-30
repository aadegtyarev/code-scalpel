import json
from notes import add, load_notes

def test_add_note():
    # Arrange
    note_text = "Тестовая заметка"
    expected_notes = [note_text]

    # Act
    add(note_text)

    # Assert
    actual_notes = load_notes()
    assert actual_notes == expected_notes