import json
import os

def add(text, storage_path='storage.json'):
    if not os.path.exists(storage_path):
        with open(storage_path, 'w') as f:
            json.dump([], f)
    with open(storage_path, 'r+') as f:
        notes = json.load(f)
        note_id = len(notes) + 1
        notes.append({'id': note_id, 'text': text})
        f.seek(0)
        json.dump(notes, f, indent=4)
        return note_id

def list_notes(storage_path='storage.json'):
    if not os.path.exists(storage_path):
        return []
    with open(storage_path, 'r') as f:
        notes = json.load(f)
    return notes

def search(query, storage_path='storage.json'):
    if not os.path.exists(storage_path):
        return []
    with open(storage_path, 'r') as f:
        notes = json.load(f)
    return [note for note in notes if query.lower() in note['text'].lower()]

def delete(note_id, storage_path='storage.json'):
    if not os.path.exists(storage_path):
        return False
    with open(storage_path, 'r+') as f:
        notes = json.load(f)
        notes = [note for note in notes if note['id'] != note_id]
        f.seek(0)
        json.dump(notes, f, indent=4)
        f.truncate()  # Clear any extra data
        return True