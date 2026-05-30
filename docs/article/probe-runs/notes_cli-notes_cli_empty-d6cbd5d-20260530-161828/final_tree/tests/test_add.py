import os
import json
from notes.add import add_note

def test_add_note():
    note = "Тестовая заметка"
    add_note(note)
    
    with open('notes.json', 'r') as f:
        notes = json.load(f)
        assert len(notes) == 1
        assert notes[0] == note
    
    # Очистим файл после теста
    os.remove('notes.json')