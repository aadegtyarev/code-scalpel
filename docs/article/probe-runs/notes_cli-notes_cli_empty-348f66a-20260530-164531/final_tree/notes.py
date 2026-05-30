import json
import os

NOTES_FILE = 'notes.json'

def add_note(text):
    if not os.path.exists(NOTES_FILE):
        notes = []
    else:
        with open(NOTES_FILE, 'r') as f:
            notes = json.load(f)
    notes.append(text)
    with open(NOTES_FILE, 'w') as f:
        json.dump(notes, f)

def list_notes():
    if not os.path.exists(NOTES_FILE):
        return []
    with open(NOTES_FILE, 'r') as f:
        notes = json.load(f)
    return notes

def search_notes(keyword):
    if not os.path.exists(NOTES_FILE):
        return []
    with open(NOTES_FILE, 'r') as f:
        notes = json.load(f)
    return [note for note in notes if keyword.lower() in note.lower()]

def delete_note(index):
    if not os.path.exists(NOTES_FILE):
        raise IndexError('No notes to delete.')
    with open(NOTES_FILE, 'r') as f:
        notes = json.load(f)
    if index < 0 or index >= len(notes):
        raise IndexError('Note index out of range.')
    del notes[index]
    with open(NOTES_FILE, 'w') as f:
        json.dump(notes, f)