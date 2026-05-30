import pytest
from notes.app import NotesApp

def test_add_note():
    app = NotesApp()
    app.add_note("Test note")
    assert "Test note" in app.list_notes()

def test_list_notes():
    app = NotesApp()
    app.add_note("Note 1")
    app.add_note("Note 2")
    notes = app.list_notes()
    assert len(notes) == 2
    assert "Note 1" in notes
    assert "Note 2" in notes