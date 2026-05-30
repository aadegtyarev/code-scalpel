import json
import os
def add_note(note):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        with open(notes_path, 'w') as f:
            json.dump([], f)
    with open(notes_path, 'r+') as f:
        notes = json.load(f)
        note_id = max([note['id'] for note in notes], default=0) + 1
        new_note = {'id': note_id, 'content': note}
        notes.append(new_note)
        f.seek(0)
        json.dump(notes, f, indent=4)
def list_notes():
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        return []
    with open(notes_path, 'r') as f:
        notes = json.load(f)
    return notes
def search_notes(keyword):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        return []
    with open(notes_path, 'r') as f:
        notes = json.load(f)
    matching_notes = [note for note in notes if keyword.lower() in note['content'].lower()]
    return matching_notes