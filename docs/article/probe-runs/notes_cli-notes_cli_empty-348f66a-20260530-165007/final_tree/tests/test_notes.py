import json
from main import add, list_notes, search_notes, delete_note

def load_notes():
    with open('notes.json', 'r') as f:
        return json.load(f)

def test_add_note():
    add('Test note 1')
    notes = load_notes()
    assert len(notes) == 1
    assert notes[0]['text'] == 'Test note 1'

def test_list_notes():
    add('Test note 2')
    output = capture_output(list_notes)
    assert 'Test note 1' in output
    assert 'Test note 2' in output

def test_search_notes():
    add('Test note 3')
    output = capture_output(search_notes, 'Test')
    assert 'Test note 1' in output
    assert 'Test note 2' in output
    assert 'Test note 3' in output

def test_delete_note():
    add('Test note 4')
    delete_note(1)
    notes = load_notes()
    assert len(notes) == 0

import io
import sys
def capture_output(func, *args):
    captured_output = io.StringIO()
    sys.stdout = captured_output
    func(*args)
    sys.stdout = sys.__stdout__
    return captured_output.getvalue()