import os
import json
from notes.add import add_note
from notes.list import list_notes

def test_list_notes():
    note = "Тестовая заметка"
    add_note(note)
    
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == note
    
    # Очистим файл после теста
    os.remove('notes.json')