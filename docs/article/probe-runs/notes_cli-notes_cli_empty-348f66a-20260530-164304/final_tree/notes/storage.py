import json
from pathlib import Path
from .note import Note
def get_storage_path():
    return Path('storage.json')

def add_note(text):
    storage_path = get_storage_path()
    notes = load_notes()
    notes.append(Note(text).text)
    save_notes(notes)

def list_notes():
    notes = load_notes()
    for index, note in enumerate(notes):
        print(f'{index}: {note}')

def search_notes(keyword):
    notes = load_notes()
    matching_notes = [note for note in notes if keyword.lower() in note.lower()]
    for index, note in enumerate(matching_notes):
        print(f'{index}: {note}')

def delete_note(index):
    storage_path = get_storage_path()
    notes = load_notes()
    if 0 <= index < len(notes):
        del notes[index]
        save_notes(notes)
    else:
        print('Invalid note index')

def load_notes():
    storage_path = get_storage_path()
    if storage_path.exists():
        with open(storage_path, 'r') as f:
            return json.load(f)
    return []

def save_notes(notes):
    storage_path = get_storage_path()
    with open(storage_path, 'w') as f:
        json.dump(notes, f, indent=4)