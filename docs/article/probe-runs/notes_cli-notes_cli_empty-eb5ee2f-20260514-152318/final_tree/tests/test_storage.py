import pytest
import json
from notes.storage import save, load

def clear_notes():
    with open('notes.json', 'w') as f:
        json.dump([], f)

@pytest.fixture(autouse=True)
def setup_teardown():
    clear_notes()
    yield
    clear_notes()

def test_save():
    notes = [{'id': 1, 'note': 'First note'}]
    save(notes)
    loaded_notes = load()
    assert loaded_notes == notes

def test_load_empty():
    loaded_notes = load()
    assert loaded_notes == []