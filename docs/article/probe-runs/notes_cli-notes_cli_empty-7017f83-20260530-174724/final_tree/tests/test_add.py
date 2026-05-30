import os
import json
from main import add_note

def test_add_note():
    note = 'Test note'
    if os.path.exists('notes.json'):
        os.remove('notes.json')
    add_note(note)
    with open('notes.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 1
    assert notes[0] == note