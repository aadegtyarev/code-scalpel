import json
from main import list_notes, add

def test_list_notes():
    add('Test note 1')
    add('Test note 2')
    notes = load_notes()
    assert len(notes) == 2
    assert notes[0] == 'Test note 1'
    assert notes[1] == 'Test note 2'
