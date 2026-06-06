import pytest
import subprocess
import json

def test_add_note():
    result = subprocess.run(['python', 'notes/cli.py', 'add', 'Тестовая заметка'], capture_output=True, text=True)
    assert result.returncode == 0
    with open('notes.json', 'r') as f:
        notes = json.load(f)
        assert len(notes) == 1
        assert notes[0] == 'Тестовая заметка'

def test_list_notes():
    subprocess.run(['python', 'notes/cli.py', 'add', 'Заметка для списка'], capture_output=True, text=True)
    result = subprocess.run(['python', 'notes/cli.py', 'list'], capture_output=True, text=True)
    assert result.returncode == 0
    assert '1. Заметка для списка' in result.stdout

def test_search_notes():
    subprocess.run(['python', 'notes/cli.py', 'add', 'Заметка для поиска'], capture_output=True, text=True)
    result = subprocess.run(['python', 'notes/cli.py', 'search', 'поиска'], capture_output=True, text=True)
    assert result.returncode == 0
    assert '1. Заметка для поиска' in result.stdout

def test_delete_note():
    subprocess.run(['python', 'notes/cli.py', 'add', 'Заметка для удаления'], capture_output=True, text=True)
    with open('notes.json', 'r') as f:
        notes = json.load(f)
        assert len(notes) == 1
    result = subprocess.run(['python', 'notes/cli.py', 'delete', '1'], capture_output=True, text=True)
    assert result.returncode == 0
    with open('notes.json', 'r') as f:
        notes = json.load(f)
        assert len(notes) == 0