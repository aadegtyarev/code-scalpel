import pytest
from notes.storage import add_note, load_notes
def test_add_note():
    add_note('Test note')
    notes = load_notes()
    assert len(notes) == 1
    assert notes[0]['text'] == 'Test note'
