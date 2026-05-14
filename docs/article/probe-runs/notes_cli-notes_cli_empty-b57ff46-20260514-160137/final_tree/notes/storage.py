import json

def load_notes():
    try:
        with open('notes.json', 'r') as f:
            return [json.loads(line) for line in f]
    except FileNotFoundError:
        return []

def save_notes(notes):
    with open('notes.json', 'w') as f:
        for note in notes:
            f.write(json.dumps(note) + '\n')