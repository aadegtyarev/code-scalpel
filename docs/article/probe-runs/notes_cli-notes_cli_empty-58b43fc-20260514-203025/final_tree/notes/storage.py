import json
import os

NOTES_FILE = 'notes.json'

def load_notes():
    if not os.path.exists(NOTES_FILE):
        return []
    with open(NOTES_FILE, 'r') as f:
        return json.load(f)

def save_notes(notes):
    with open(NOTES_FILE, 'w') as f:
        json.dump(notes, f, indent=4)

def add_note(note):
    notes = load_notes()
    notes.append(note)
    save_notes(notes)

def list_notes():
    return load_notes()

def search_notes(query):
    notes = load_notes()
    return [note for note in notes if query.lower() in note.lower()]

def delete_note(index):
    notes = load_notes()
    if 0 <= index < len(notes):
        del notes[index]
        save_notes(notes)
    else:
        raise IndexError('Note index out of range')