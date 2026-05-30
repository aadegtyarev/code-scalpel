import json
import os

def _get_storage_path():
    return 'storage.json'

def add_note(text):
    notes = load_notes()
    notes.append({'text': text})
    save_notes(notes)

def load_notes():
    path = _get_storage_path()
    if os.path.exists(path):
        with open(path, 'r') as f:
            return json.load(f)
    return []

def save_notes(notes):
    with open(_get_storage_path(), 'w') as f:
        json.dump(notes, f, indent=4)