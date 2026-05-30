import pytest
import json
import os
from notes.notes import add_note, list_notes, search_notes

def test_add_note():
    # Очистить хранилище перед запуском теста
    if os.path.exists('notes.json'):
        os.remove('notes.json')

    note_content = 'Test note'
    add_note(note_content)
    with open('notes.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 1
    assert notes[0]['id'] == 1
    assert notes[0]['content'] == note_content
def test_list_notes():
    # Очистить хранилище перед запуском теста
    if os.path.exists('notes.json'):
        os.remove('notes.json')

    add_note('Note 1')
    add_note('Note 2')
    notes = list_notes()
    assert len(notes) == 2
    assert notes[0]['id'] == 1
    assert notes[0]['content'] == 'Note 1'
    assert notes[1]['id'] == 2
    assert notes[1]['content'] == 'Note 2'
def test_search_notes():
    # Очистить хранилище перед запуском теста
    if os.path.exists('notes.json'):
        os.remove('notes.json')

    add_note('Test note 1')
    add_note('Another test note')
    add_note('Irrelevant note')
    matching_notes = search_notes('test')
    assert len(matching_notes) == 2
    assert any(note['content'] == 'Test note 1' for note in matching_notes)
    assert any(note['content'] == 'Another test note' for note in matching_notes)
    assert not any(note['content'] == 'Irrelevant note' for note in matching_notes)