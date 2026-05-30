import json
import os

def add(text):
    storage_path = 'storage.json'
    if not os.path.exists(storage_path):
        with open(storage_path, 'w') as f:
            json.dump([], f)
    with open(storage_path, 'r+') as f:
        notes = json.load(f)
        if text not in notes:
            notes.append(text)
            f.seek(0)
            json.dump(notes, f)


def list_notes():
    storage_path = 'storage.json'
    if not os.path.exists(storage_path):
        return []
    with open(storage_path, 'r') as f:
        notes = json.load(f)
    return notes


def search(query):
    storage_path = 'storage.json'
    if not os.path.exists(storage_path):
        return []
    with open(storage_path, 'r') as f:
        notes = json.load(f)
    return [note for note in notes if query.lower() in note.lower()]


def delete(index):
    storage_path = 'storage.json'
    if not os.path.exists(storage_path):
        return
    with open(storage_path, 'r+') as f:
        notes = json.load(f)
        if 0 <= index < len(notes):
            del notes[index]
            f.seek(0)
            json.dump(notes, f)