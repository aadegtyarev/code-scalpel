import json
import os

def add_note(note):
    notes = load_notes()
    notes.append(note)
    save_notes(notes)

def list_notes():
    return load_notes()

def search_notes(keyword):
    notes = load_notes()
    return [note for note in notes if keyword in note]

def delete_note(index):
    notes = load_notes()
    if 0 <= index < len(notes):
        del notes[index]
        save_notes(notes)

def load_notes():
    if os.path.exists('storage.json'):
        with open('storage.json', 'r') as f:
            return json.load(f)
    return []

def save_notes(notes):
    with open('storage.json', 'w') as f:
        json.dump(notes, f)
