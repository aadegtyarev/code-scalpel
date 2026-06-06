import pytest
from notes_app.storage import Storage
from notes_app.service import NoteService

@pytest.fixture
def service(tmp_path):
    db_file = tmp_path / "test_notes.json"
    storage = Storage(str(db_file))
    return NoteService(storage)

def test_add_note_success(service):
    note = service.add_note("Hello world")
    assert note["text"] == "Hello world"
    assert note["id"] == 1
    assert len(service.list_notes()) == 1

def test_add_note_empty_error(service):
    with pytest.raises(ValueError, match="Note text cannot be empty"):
        service.add_note("   ")

def test_search_notes(service):
    service.add_note("Apple pie")
    service.add_note("Banana bread")
    service.add_note("Cherry tart")
    
    results = service.search_notes("apple")
    assert len(results) == 1
    assert results[0]["text"] == "Apple pie"
    
    results_all = service.search_notes("")
    assert len(results_all) == 3

def test_delete_note_service(service):
    service.add_note("To delete")
    note = service.list_notes()[0]
    assert service.delete_note(note["id"]) is True
    assert len(service.list_notes()) == 0

def test_delete_nonexistent_note(service):
    assert service.delete_note(99) is False
