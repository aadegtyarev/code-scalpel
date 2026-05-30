import pytest
import json
from notes.cli import add, load_notes

def test_add_note(tmp_path):
    notes_file = tmp_path / 'notes.json'
    with open(notes_file, 'w') as f:
        json.dump({}, f)
    add('Тестовая заметка', notes_file=str(notes_file))
    notes = load_notes(str(notes_file))
    assert len(notes) == 1
    assert notes['1'] == 'Тестовая заметка'
