import pytest
import json
from notes.storage import load_notes, add_note

def test_add_note():
    # Очистка хранилища перед тестом
    with open('storage.json', 'w') as f:
        json.dump([], f)

    add_note('Пример заметки')
    notes = load_notes()
    assert len(notes) == 1
    assert notes[0]['text'] == 'Пример заметки'
