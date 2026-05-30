import pytest
from notes import add_note, list_notes, search_notes, delete_note

def setup_module():
    with open('notes.json', 'w') as f:
        json.dump([], f)
