import pytest
import json
from notes.cli import add

def test_add():
    add("Test note")
    with open('storage.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 1
    assert notes[0] == "Test note"
