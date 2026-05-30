import json
import os

def add_note(note):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        with open(notes_path, 'w') as f:
            json.dump([], f)
    
    with open(notes_path, 'r+') as f:
        notes = json.load(f)
        notes.append(note)
        f.seek(0)
        json.dump(notes, f)