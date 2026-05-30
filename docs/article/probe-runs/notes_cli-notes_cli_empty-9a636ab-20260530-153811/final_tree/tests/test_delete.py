import pytest
from notes.cli import delete_note, add_note, load_notes

def test_delete_single_note(capsys):
    add_note('Test note')
    initial_notes = load_notes()
    delete_note(1)
    updated_notes = load_notes()
    captured = capsys.readouterr()
    assert len(updated_notes) == len(initial_notes) - 1
    assert 'Note deleted: Test note' in captured.out

def test_delete_multiple_notes(capsys):
    add_note('Note 1')
    add_note('Note 2')
    delete_note(1)
    updated_notes = load_notes()
    captured = capsys.readouterr()
    assert len(updated_notes) == 1
    assert 'Note deleted: Note 1' in captured.out
    assert 'Note 2' in updated_notes[0]

def test_delete_invalid_index(capsys):
    delete_note(1)
    captured = capsys.readouterr()
    assert 'Invalid note index.' in captured.out