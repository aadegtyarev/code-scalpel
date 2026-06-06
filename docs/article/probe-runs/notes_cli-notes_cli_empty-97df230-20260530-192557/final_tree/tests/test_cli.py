import json
import pytest
from notes.cli import add_note, list_notes, search_notes, delete_note

def setup_module():
    if os.path.exists('notes.json'):
        os.remove('notes.json')

def test_add_note():
    add_note('Test note 1')
    with open('notes.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 1
    assert notes[0] == 'Test note 1'

def test_list_notes():
    add_note('Test note 2')
    output = capture_output(list_notes)
    assert '1. Test note 1' in output
    assert '2. Test note 2' in output

def test_search_notes():
    add_note('Test note 3')
    output = capture_output(search_notes, 'test')
    assert '1. Test note 1' in output
    assert '2. Test note 2' in output
    assert '3. Test note 3' in output

def test_delete_note():
    add_note('Test note 4')
    delete_note(1)
    with open('notes.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 0