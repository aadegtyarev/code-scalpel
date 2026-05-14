import pytest
import subprocess
import os
import json

def test_add_note():
    # Arrange
    note_content = 'This is a test note'
    notes_path = 'notes.json'
    if os.path.exists(notes_path):
        os.remove(notes_path)
    
    # Act
    subprocess.run(['python', '-m', 'notes.cli', 'add', note_content])
    
    # Assert
    assert os.path.exists(notes_path)
    with open(notes_path, 'r') as f:
        notes = json.load(f)
        assert len(notes) == 1
        assert notes[0] == note_content

def test_list_notes():
    # Arrange
    note_content = 'This is a test note'
    notes_path = 'notes.json'
    if os.path.exists(notes_path):
        os.remove(notes_path)
    subprocess.run(['python', '-m', 'notes.cli', 'add', note_content])
    
    # Act
    result = subprocess.run(['python', '-m', 'notes.cli', 'list'], capture_output=True, text=True)
    
    # Assert
    assert note_content in result.stdout

def test_search_notes():
    # Arrange
    note_content = 'This is a test note'
    notes_path = 'notes.json'
    if os.path.exists(notes_path):
        os.remove(notes_path)
    subprocess.run(['python', '-m', 'notes.cli', 'add', note_content])
    
    # Act
    result = subprocess.run(['python', '-m', 'notes.cli', 'search', 'test'], capture_output=True, text=True)
    
    # Assert
    assert note_content in result.stdout