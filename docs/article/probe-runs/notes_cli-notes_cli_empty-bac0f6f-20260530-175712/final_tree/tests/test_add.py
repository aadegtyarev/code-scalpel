import os
import json
from notes.cli import add_note

def test_add_note():
    note_text = 'Test Note'
    add_note(note_text)
    with open('notes.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 1
    assert notes[0] == note_text

    # Clean up after test
    os.remove('notes.json')