import json

def save_notes(notes):
    with open('notes.json', 'w') as f:
        json.dump(notes, f)

def load_notes():
    try:
        with open('notes.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []