import pytest
from notes.storage import Storage
import subprocess
import tempfile
import sys
import os

def test_add():
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        storage = Storage(filepath=temp_file.name)
        original_cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__) + '/../')
            result = subprocess.run(['python', 'notes/cli.py', 'add', 'Test Note'], capture_output=True, text=True)
        finally:
            os.chdir(original_cwd)
        assert result.returncode == 0
        notes = storage.list()
        assert len(notes) == 1
        assert notes[0]['id'] == 1
        assert notes[0]['text'] == 'Test Note'

def test_list():
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        storage = Storage(filepath=temp_file.name)
        storage.add('Note 1')
        storage.add('Note 2')
        original_cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__) + '/../')
            result = subprocess.run(['python', 'notes/cli.py', 'list'], capture_output=True, text=True)
        finally:
            os.chdir(original_cwd)
        assert result.returncode == 0
        assert 'Note 1' in result.stdout
        assert 'Note 2' in result.stdout

def test_search():
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        storage = Storage(filepath=temp_file.name)
        storage.add('Test Note')
        original_cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__) + '/../')
            result = subprocess.run(['python', 'notes/cli.py', 'search', 'Test'], capture_output=True, text=True)
        finally:
            os.chdir(original_cwd)
        assert result.returncode == 0
        assert 'Test Note' in result.stdout
        result = subprocess.run(['python', 'notes/cli.py', 'search', 'Nonexistent'], capture_output=True, text=True)
        assert result.returncode == 0
        assert 'No notes found containing the keyword.' in result.stdout

def test_delete():
    with tempfile.NamedTemporaryFile(delete=False) as temp_file:
        storage = Storage(filepath=temp_file.name)
        note_id = storage.add('Note to Delete')
        original_cwd = os.getcwd()
        try:
            os.chdir(os.path.dirname(__file__) + '/../')
            result = subprocess.run(['python', 'notes/cli.py', 'delete', str(note_id)], capture_output=True, text=True)
        finally:
            os.chdir(original_cwd)
        assert result.returncode == 0
        notes = storage.list()
        assert len(notes) == 0