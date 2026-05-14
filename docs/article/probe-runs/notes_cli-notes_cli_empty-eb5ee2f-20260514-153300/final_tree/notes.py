# notes.py
import json

def add_note(note):
    with open('storage.json', 'r') as f:
        data = json.load(f)
    data.append({'note': note})
    with open('storage.json', 'w') as f:
        json.dump(data, f)

def list_notes():
    with open('storage.json', 'r') as f:
        data = json.load(f)
    return data

def search_notes(query):
    with open('storage.json', 'r') as f:
        data = json.load(f)
    return [note for note in data if query.lower() in note['note'].lower()]

def delete_note(note_id):
    with open('storage.json', 'r') as f:
        data = json.load(f)
    data.pop(note_id)
    with open('storage.json', 'w') as f:
        json.dump(data, f)