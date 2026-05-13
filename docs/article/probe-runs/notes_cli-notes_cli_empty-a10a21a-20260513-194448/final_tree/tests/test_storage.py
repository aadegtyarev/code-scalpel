import pytest
from notetool.storage import JsonStorage

def test_add_note(storage):
    storage.add_note("First note")
    notes = storage.get_notes()
    assert notes == ["First note"]

def test_get_notes(storage):
    storage.add_note("Second note")
    notes = storage.get_notes()
    assert notes == ["Second note"]

def test_delete_note(storage):
    storage.add_note("Third note")
    storage.delete_note(0)
    notes = storage.get_notes()
    assert notes == []