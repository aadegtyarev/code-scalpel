import json
import os

def add_note(note):
    notes = get_notes()
    notes.append(note)
    save_notes(notes)

def get_notes():
    if not os.path.exists('notes.json'):
        return []
    with open('notes.json', 'r') as f:
        return json.load(f)

def save_notes(notes):
    with open('notes.json', 'w') as f:
        json.dump(notes, f, indent=4)

def search_notes(keyword):
    notes = get_notes()
    return [note for note in notes if keyword.lower() in note.lower()]

def delete_note(index):
    notes = get_notes()
    if 0 <= index < len(notes):
        del notes[index]
        save_notes(notes)
