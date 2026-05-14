import pytest
from notes.cli import main
import os
import json

def setup_module(module):
    if os.path.exists('notes.json'):
        os.remove('notes.json')

def test_add_note(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(['add', 'Test note'])
    assert excinfo.value.code == 0
    with open('notes.json', 'r') as file:
        notes = json.load(file)
    assert len(notes) == 1
    assert notes[0] == 'Test note'

def test_list_notes(capsys):
    main(['add', 'Test note'])
    with pytest.raises(SystemExit) as excinfo:
        main(['list'])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert 'Test note' in captured.out