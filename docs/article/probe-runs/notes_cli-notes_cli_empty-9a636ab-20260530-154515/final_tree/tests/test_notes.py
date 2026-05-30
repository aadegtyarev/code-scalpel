import pytest
from notes.cli import main
import json
def test_add_command(tmp_path):
    storage_path = tmp_path / 'notes.json'
    result = main(['add', 'Test note 1'], storage_path=str(storage_path))
    assert result == 0
    with open(storage_path, 'r') as f:
        notes = json.load(f)
    assert len(notes) == 1
    assert notes[0]['text'] == 'Test note 1'

def test_list_command(tmp_path):
    storage_path = tmp_path / 'notes.json'
    main(['add', 'Test note 1'], storage_path=str(storage_path))
    result = main(['list'], storage_path=str(storage_path))
    assert result == 0

def test_search_command(tmp_path):
    storage_path = tmp_path / 'notes.json'
    main(['add', 'Test note 1'], storage_path=str(storage_path))
    result = main(['search', 'Test'], storage_path=str(storage_path))
    assert result == 0

def test_delete_command(tmp_path):
    storage_path = tmp_path / 'notes.json'
    main(['add', 'Test note 1'], storage_path=str(storage_path))
    result = main(['delete', '0'], storage_path=str(storage_path))
    assert result == 0
    with open(storage_path, 'r') as f:
        notes = json.load(f)
    assert len(notes) == 0