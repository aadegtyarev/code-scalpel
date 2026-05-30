import pytest
from notes.storage import add_note, list_notes, delete_note
def test_delete_note():
    add_note('Test note 1')
    add_note('Test note 2')
    delete_note(0)
    output = list_notes()
    assert '0: Test note 2' in output
    assert 'Test note 1' not in output