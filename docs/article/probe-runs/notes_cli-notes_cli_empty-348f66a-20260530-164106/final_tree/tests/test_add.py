import json
from main import add, load_notes

def test_add_note():
    add('Test note')
    notes = load_notes()
    assert len(notes) == 1
    assert notes[0] == 'Test note'
