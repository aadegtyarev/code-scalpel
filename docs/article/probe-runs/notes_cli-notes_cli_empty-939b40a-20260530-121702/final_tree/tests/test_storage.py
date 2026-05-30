import json
from unittest.mock import patch, mock_open
from storage import load_notes, save_notes, add_note, get_notes, search_notes, delete_note

def test_load_notes_empty():
    with patch('storage.open', return_value=mock_open(read_data='[]')) as mock_file:
        assert load_notes() == []
        mock_file.assert_called_once_with('notes.json', 'r')

def test_load_notes_with_data():
    with patch('storage.open', return_value=mock_open(read_data='["Note 1", "Note 2"]')) as mock_file:
        assert load_notes() == ['Note 1', 'Note 2']
        mock_file.assert_called_once_with('notes.json', 'r')

def test_save_notes():
    with patch('storage.open', return_value=mock_open()) as mock_file:
        save_notes(['Note 1'])
        mock_file.assert_called_once_with('notes.json', 'w')
        mock_file().write.assert_called_once_with('["Note 1"]')

def test_add_note():
    add_note('New Note')
    notes = load_notes()
    assert notes == ['New Note']

def test_get_notes():
    add_note('Note 1')
    add_note('Note 2')
    assert get_notes() == ['Note 1', 'Note 2']

def test_search_notes():
    add_note('Note with keyword')
    add_note('Another note')
    results = search_notes('keyword')
    assert results == ['Note with keyword']

def test_delete_note():
    add_note('Note 1')
    add_note('Note 2')
    delete_note(0)
    notes = get_notes()
    assert notes == ['Note 2']