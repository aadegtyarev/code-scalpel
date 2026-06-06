import json
import os

def add(note):
    notes = load_notes()
    notes.append(note)
    save_notes(notes)

def list_notes():
    return load_notes()

def search(query):
    notes = load_notes()
    return [note for note in notes if query.lower() in note.lower()]

def delete(index):
    notes = load_notes()
    if 0 <= index < len(notes):
        del notes[index]
        save_notes(notes)

def load_notes():
    if os.path.exists('notes.json'):
        with open('notes.json', 'r') as file:
            return json.load(file)
    return []

def save_notes(notes):
    with open('notes.json', 'w') as file:
        json.dump(notes, file, indent=4)