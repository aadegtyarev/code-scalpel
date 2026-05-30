import pytest
from notes.cli import search_notes, add_note, load_notes

def test_search_empty_notes(capsys):
    load_notes()  # Ensure the notes file is empty
    search_notes('test')
    captured = capsys.readouterr()
    assert 'No matching notes found.' in captured.out

def test_search_single_note(capsys):
    add_note('Test note')
    search_notes('test')
    captured = capsys.readouterr()
    assert '1: Test note' in captured.out

def test_search_multiple_notes(capsys):
    add_note('Note 1')
    add_note('Note 2 with test keyword')
    search_notes('test')
    captured = capsys.readouterr()
    assert '1: Note 1' in captured.out
    assert '2: Note 2 with test keyword' in captured.out