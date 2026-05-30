import json
import os

def add_note(note_text):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        with open(notes_path, 'w') as f:
            json.dump([], f)
    with open(notes_path, 'r+') as f:
        notes = json.load(f)
        new_note = {
            'id': len(notes) + 1,
            'text': note_text
        }
        if any(note['id'] == new_note['id'] for note in notes):
            new_note['id'] += 1
        notes.append(new_note)
        f.seek(0)
        json.dump(notes, f, indent=4)

def list_notes():
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        print('Нет заметок.')
        return
    with open(notes_path, 'r') as f:
        notes = json.load(f)
    for note in notes:
        print(f'{note['id']}: {note['text']}')

def search_notes(keyword):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        print('Нет заметок.')
        return
    with open(notes_path, 'r') as f:
        notes = json.load(f)
    found_notes = [note for note in notes if keyword.lower() in note['text'].lower()]
    if not found_notes:
        print('Заметки не найдены.')
        return
    for note in found_notes:
        print(f'{note['id']}: {note['text']}')

def delete_note(note_id):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        print('Нет заметок.')
        return
    with open(notes_path, 'r+') as f:
        notes = json.load(f)
        notes = [note for note in notes if note['id'] != note_id]
        f.seek(0)
        json.dump(notes, f, indent=4)