import json
import os

def load_notes():
    if not os.path.exists('notes.json'):
        return []
    with open('notes.json', 'r') as file:
        return json.load(file)

def save_notes(notes):
    with open('notes.json', 'w') as file:
        json.dump(notes, file, indent=4)