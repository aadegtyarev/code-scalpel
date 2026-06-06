import json
import os

def add_note(note_text):
    notes_file = 'notes.json'
    if not os.path.exists(notes_file):
        with open(notes_file, 'w') as f:
            json.dump([], f)
    with open(notes_file, 'r+') as f:
        notes = json.load(f)
        notes.append(note_text)
        f.seek(0)
        json.dump(notes, f, indent=4)

def list_notes():
    notes_file = 'notes.json'
    if not os.path.exists(notes_file):
        print('No notes found.')
        return
    with open(notes_file, 'r') as f:
        notes = json.load(f)
        for i, note in enumerate(notes, start=1):
            print(f'{i}. {note}')

def search_notes(keyword):
    notes_file = 'notes.json'
    if not os.path.exists(notes_file):
        print('No notes found.')
        return
    with open(notes_file, 'r') as f:
        notes = json.load(f)
        matching_notes = [note for note in notes if keyword.lower() in note.lower()]
        if not matching_notes:
            print('No matching notes found.')
            return
        for i, note in enumerate(matching_notes, start=1):
            print(f'{i}. {note}')

def delete_note(index):
    notes_file = 'notes.json'
    if not os.path.exists(notes_file):
        print('No notes found.')
        return
    with open(notes_file, 'r+') as f:
        notes = json.load(f)
        if 1 <= index <= len(notes):
            del notes[index - 1]
            f.seek(0)
            json.dump(notes, f, indent=4)
            print('Note deleted.')
        else:
            print('Invalid note index.')