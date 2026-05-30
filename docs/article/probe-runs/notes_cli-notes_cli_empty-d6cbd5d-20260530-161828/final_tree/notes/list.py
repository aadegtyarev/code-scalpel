import json
import os

def list_notes():
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        return []
    
    with open(notes_path, 'r') as f:
        notes = json.load(f)
        return notes