import pytest
from notes.cli import search

def test_search():
    add("Test note")
    captured_output = capture_stdout(search, "test")
    assert captured_output.strip() == "1. Test note"
