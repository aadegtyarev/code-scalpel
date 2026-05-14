import pytest
from notepad.cli import NotepadCLI

@pytest.fixture(autouse=True)
def clear_storage():
    cli = NotepadCLI()
    cli.storage.notes = []

def test_add_note(clear_storage):
    cli = NotepadCLI()
    cli.add("First note")
    notes = cli.list()
    assert len(notes) == 1
    assert "First note" in notes[0]
