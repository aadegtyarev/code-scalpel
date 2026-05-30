import os
import json
from main import add_note, list_notes

def test_list_notes(capsys):
    note = 'Test note'
    if os.path.exists('notes.json'):
        os.remove('notes.json')
    add_note(note)
    list_notes()
    captured = capsys.readouterr()
    assert captured.out.strip() == '1. Test note'