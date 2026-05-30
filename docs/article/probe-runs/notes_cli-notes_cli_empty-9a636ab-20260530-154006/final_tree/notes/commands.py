import json
import os

def add(text):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        with open(notes_path, 'w') as f:
            json.dump([], f)
    with open(notes_path, 'r+') as f:
        notes = json.load(f)
        notes.append({'text': text})
        f.seek(0)
        json.dump(notes, f, indent=4)

def list_notes():
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        return []
    with open(notes_path, 'r') as f:
        notes = json.load(f)
    return notes