import pytest
from notes.cli import list_notes, add
def test_list():
    add("Test note")
    captured_output = capture_stdout(list_notes)
    assert captured_output.strip() == "1. Test note"
