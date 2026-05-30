import pytest
from notes import add_note, list_notes
import json

def setup_module(module):
    try:
        with open('storage.json', 'w') as file:
            json.dump({}, file)
    except FileNotFoundError:
        pass

def test_add_new_note():
    add_note('Test Note 1', 'This is a test note.')
    with open('storage.json', 'r') as file:
        notes = json.load(file)
    assert 'Test Note 1' in notes and notes['Test Note 1'] == 'This is a test note.'

def test_add_existing_note():
    add_note('Test Note 2', 'This is another test note.')
    with pytest.raises(FileNotFoundError):
        add_note('Test Note 2', 'Trying to overwrite the existing note.')

def test_list_notes(capsys):
    add_note('Test Note 3', 'This is a third test note.')
    list_notes()
    captured = capsys.readouterr()
    assert 'Заметка 