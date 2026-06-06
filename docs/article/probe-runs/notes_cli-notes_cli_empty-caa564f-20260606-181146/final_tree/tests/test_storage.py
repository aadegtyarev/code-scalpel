from storage import add_note, list_notes, search_notes, delete_note

def test_add_note():
    add_note("Test note")
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0] == "Test note"

def test_list_notes():
    add_note("Note 1")
    add_note("Note 2")
    notes = list_notes()
    assert len(notes) == 2
    assert notes[0] == "Note 1"
    assert notes[1] == "Note 2"

def test_search_notes():
    add_note("Test note")
    results = search_notes("test")
    assert len(results) == 1
    assert results[0] == "Test note"

def test_delete_note():
    add_note("Note to delete")
    index_to_delete = 0
    delete_note(index_to_delete)
    updated_notes = list_notes()
    assert len(updated_notes) == 0