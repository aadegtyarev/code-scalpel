import os
import json
from notes.commands import add, list_notes, search_notes, delete_note

def test_add_note():
    note_text = 'Тестовая заметка'
    add(note_text)
    with open('notes.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 1
    assert notes[0]['text'] == note_text

def test_list_notes():
    add('Заметка 1')
    add('Заметка 2')
    notes = list_notes()
    assert len(notes) == 2
    assert notes[0]['text'] == 'Заметка 1'
    assert notes[1]['text'] == 'Заметка 2'

def test_search_notes():
    add('Заметка 1')
    add('Заметка 2')
    results = search_notes('1')
    assert len(results) == 1
    assert results[0]['text'] == 'Заметка 1'

def test_delete_note():
    add('Заметка 1')
    add('Заметка 2')
    delete_note(0)
    with open('notes.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 1
    assert notes[0]['text'] == 'Заметка 2'