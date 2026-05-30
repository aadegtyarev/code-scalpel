import pytest
from notes.cli import delete

def test_delete():
    add("Test note")
    delete(1)
    with open('storage.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 0
