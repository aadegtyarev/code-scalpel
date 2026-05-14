import pytest
from notepad.cli import NotepadCLI

def test_delete_note():
    cli = NotepadCLI()
    cli.add("First note")
    cli.add("Second note")
    cli.delete(1)
    notes = cli.list()
    assert len(notes) == 1
    assert "First note" not in notes[0]
