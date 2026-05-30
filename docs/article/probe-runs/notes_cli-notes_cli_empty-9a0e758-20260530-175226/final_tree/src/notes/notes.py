import json
import os
def add_note(text):
    notes = load_notes()
    notes.append(text)
    save_notes(notes)
def list_notes():
    return load_notes()
def search_notes(keyword):
    notes = load_notes()
    return [note for note in notes if keyword.lower() in note.lower()]
def delete_note(index):
    notes = load_notes()
    if 0 <= index < len(notes):
        del notes[index]
        save_notes(notes)
def load_notes():
    if not os.path.exists('notes.json'):
        return []
    with open('notes.json', 'r') as file:
        return json.load(file)
def save_notes(notes):
    with open('notes.json', 'w') as file:
        json.dump(notes, file, indent=4)