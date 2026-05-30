import pytest
from notes.cli import list_notes, load_notes

def test_list_empty_notes(capsys):
    load_notes()  # Ensure the notes file is empty
    list_notes()
    captured = capsys.readouterr()
    assert 'No notes found.' in captured.out

def test_list_single_note(capsys):
    add_note('Test note')
    list_notes()
    captured = capsys.readouterr()
    assert '1: Test note' in captured.out

def test_list_multiple_notes(capsys):
    add_note('Note 1')
    add_note('Note 2')
    list_notes()
    captured = capsys.readouterr()
    assert '1: Note 1' in captured.out
    assert '2: Note 2' in captured.out