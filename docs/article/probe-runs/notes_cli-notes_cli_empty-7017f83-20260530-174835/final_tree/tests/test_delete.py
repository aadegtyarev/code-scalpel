import json
from notes import add, delete, load_notes

def test_delete(capsys):
    # Arrange
    note_text = "Тестовая заметка"
    add(note_text)
    notes = load_notes()
    index_to_delete = 1
    expected_output = f"Заметка удалена: {notes[index_to_delete - 1]}\n"

    # Act
    delete(index_to_delete)
    captured = capsys.readouterr()

    # Assert
    assert captured.out == expected_output