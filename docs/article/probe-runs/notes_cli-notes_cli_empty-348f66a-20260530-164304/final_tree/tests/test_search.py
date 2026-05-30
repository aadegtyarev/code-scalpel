import pytest
from notes.storage import add_note, search_notes
def test_search_notes():
    add_note('Test note 1')
    add_note('Another test note')
    add_note('Test note 2')
    output = search_notes('test')
    assert '0: Test note 1' in output
    assert '1: Another test note' in output
    assert '2: Test note 2' in output