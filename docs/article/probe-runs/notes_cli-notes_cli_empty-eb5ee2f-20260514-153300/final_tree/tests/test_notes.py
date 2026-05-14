import json
from notes import add_note, list_notes, search_notes, delete_note

def clear_storage():
    with open('storage.json', 'w') as f:
        json.dump([], f)

def test_add_note():
    clear_storage()
    add_note('Test note')
    with open('storage.json', 'r') as f:
        data = json.load(f)
    assert len(data) == 1
    assert data[0]['note'] == 'Test note'

def test_list_notes():
    clear_storage()
    notes = list_notes()
    assert isinstance(notes, list)

def test_search_notes():
    clear_storage()
    add_note('Searchable note')
    results = search_notes('Searchable')
    assert len(results) == 1
    assert results[0]['note'] == 'Searchable note'

def test_delete_note():
    clear_storage()
    add_note('Deletable note')
    delete_note(0)
    with open('storage.json', 'r') as f:
        data = json.load(f)
    assert len(data) == 0