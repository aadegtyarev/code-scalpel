import json
from main import delete, add, load_notes

def test_delete_note():
    add('Test note 1')
    add('Test note 2')
    delete(1)
    notes = load_notes()
    assert len(notes) == 1
    assert notes[0] == 'Test note 2'
