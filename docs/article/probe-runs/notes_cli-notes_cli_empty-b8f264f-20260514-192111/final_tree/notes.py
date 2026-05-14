# notes.py
import json
def add_note(note):
    with open('storage.json', 'r') as file:
        notes = json.load(file)
    
    notes.append(note)
    
    with open('storage.json', 'w') as file:
        json.dump(notes, file)
def list_notes():
    with open('storage.json', 'r') as file:
        notes = json.load(file)
    return notes
def search_notes(keyword):
    pass
def delete_note(index):
    pass