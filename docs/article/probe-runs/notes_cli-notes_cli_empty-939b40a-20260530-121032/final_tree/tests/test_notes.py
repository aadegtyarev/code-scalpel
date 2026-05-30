import pytest
import json
from notes import add_note, list_notes, search_notes, delete_note

def test_add_note():
    add_note('Test note')
    with open('notes.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 1
    assert notes[0]['text'] == 'Test note'

def test_list_notes(capsys):
    add_note('First note')
    add_note('Second note')
    list_notes()
    captured = capsys.readouterr()
    assert '1: First note' in captured.out
    assert '2: Second note' in captured.out

def test_search_notes(capsys):
    add_note('Test search')
    search_notes('search')
    captured = capsys.readouterr()
    assert '1: Test search' in captured.out

def test_delete_note():
    add_note('Note to delete')
    delete_note(1)
    with open('notes.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 0