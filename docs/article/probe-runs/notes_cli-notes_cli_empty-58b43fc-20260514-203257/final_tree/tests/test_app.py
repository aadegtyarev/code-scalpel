import pytest
import json
from app import main, add_note
def test_add_note():
    note = "Пример заметки"
    add_note(note)
    with open('data/notes.json', 'r') as file:
        notes = json.load(file)
    assert notes == [note]