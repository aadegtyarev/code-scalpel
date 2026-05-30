import pytest
from unittest.mock import patch, mock_open
from notes_cli import main

def test_add_note(capsys):
    with patch('notes_cli.add_note') as add_mock:
        with patch('sys.argv', ['notes_cli.py', 'add', 'New Note']):
            main()
        add_mock.assert_called_once_with('New Note')
        captured = capsys.readouterr()
        assert captured.out == ''


def test_list_notes(capsys):
    with patch('notes_cli.get_notes', return_value=['Note 1', 'Note 2']):
        with patch('sys.argv', ['notes_cli.py', 'list']):
            main()
        captured = capsys.readouterr()
        assert captured.out == 'Note 1\nNote 2\n'


def test_search_notes(capsys):
    with patch('notes_cli.search_notes', return_value=['Note with keyword']):
        with patch('sys.argv', ['notes_cli.py', 'search', 'keyword']):
            main()
        captured = capsys.readouterr()
        assert captured.out == 'Note with keyword\n'


def test_delete_note(capsys):
    with patch('notes_cli.delete_note') as delete_mock:
        with patch('sys.argv', ['notes_cli.py', 'delete', '0']):
            main()
        delete_mock.assert_called_once_with(0)
        captured = capsys.readouterr()
        assert captured.out == ''