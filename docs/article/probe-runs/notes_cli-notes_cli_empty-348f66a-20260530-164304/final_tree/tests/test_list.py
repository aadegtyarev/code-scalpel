import pytest
from notes.storage import list_notes
def test_list_notes():
    add_note('Test note 1')
    add_note('Test note 2')
    output = list_notes()
    assert '0: Test note 1' in output
    assert '1: Test note 2' in output
