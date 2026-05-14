import json

def save(notes):
    with open('notes.json', 'w') as f:
        json.dump(notes, f)

def load():
    try:
        with open('notes.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []