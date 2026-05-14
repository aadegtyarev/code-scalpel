import pytest
from notepad.cli import NotepadCLI

def test_list_notes():
    cli = NotepadCLI()
    cli.add("First note")
    cli.add("Second note")
    notes = cli.list()
    assert len(notes) == 2
    assert "First note" in notes[0]
    assert "Second note" in notes[1]
