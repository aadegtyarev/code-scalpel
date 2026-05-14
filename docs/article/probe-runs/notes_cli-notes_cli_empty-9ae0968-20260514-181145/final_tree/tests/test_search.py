import pytest
from notepad.cli import NotepadCLI

def test_search_notes():
    cli = NotepadCLI()
    cli.add("First note")
    cli.add("Second note with keyword")
    notes = cli.search("keyword")
    assert len(notes) == 1
    assert "Second note with keyword" in notes[0]
