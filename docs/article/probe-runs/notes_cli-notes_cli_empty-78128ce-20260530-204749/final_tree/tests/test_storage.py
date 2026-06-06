import pytest
from notes_app.storage import Storage

@pytest.fixture
def temp_storage(tmp_path):
    db_file = tmp_path / "test_notes.json"
    return Storage(str(db_file))

def test_add_note(temp_storage):
    note = {"id": 1, "text": "Test note"}
    temp_storage.add(note)
    notes = temp_storage.get_all()
    assert len(notes) == 1
    assert notes[0]["text"] == "Test note"

def test_get_all_empty(temp_storage):
    assert temp_storage.get_all() == []

def test_delete_note(temp_storage):
    note = {"id": 1, "text": "To be deleted"}
    temp_storage.add(note)
    assert temp_storage.delete(1) is True
    assert len(temp_storage.get_all()) == 0

def test_delete_nonexistent_note(temp_storage):
    note = {"id": 1, "text": "Keep me"}
    temp_storage.add(note)
    assert temp_storage.delete(999) is False
    assert len(temp_storage.get_all()) == 1

def test_persistence(tmp_path):
    db_file = tmp_path / "persist.json"
    storage = Storage(str(db_file))
    note = {"id": 5, "text": "Persistent note"}
    storage.add(note)
    
    # New instance reading same file
    new_storage = Storage(str(db_file))
    notes = new_storage.get_all()
    assert len(notes) == 1
    assert notes[0]["id"] == 5
