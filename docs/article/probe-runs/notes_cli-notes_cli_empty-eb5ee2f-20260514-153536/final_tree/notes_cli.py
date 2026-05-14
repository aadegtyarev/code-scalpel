#!/usr/bin/env python3
import notes_storage

def add_note(note):
    notes = notes_storage.load_notes()
    notes.append({'id': len(notes) + 1, 'note': note})
    notes_storage.save_notes(notes)
    print('Note added successfully.')

def list_notes():
    notes = notes_storage.load_notes()
    if not notes:
        print('No notes available.')
    else:
        for note in notes:
            print(f'{note['id']}: {note['note']}')

def search_notes(query):
    notes = notes_storage.load_notes()
    matching_notes = [note for note in notes if query.lower() in note['note'].lower()]
    if not matching_notes:
        print('No matching notes found.')
    else:
        for note in matching_notes:
            print(f'{note['id']}: {note['note']}')

def delete_note(note_id):
    notes = notes_storage.load_notes()
    notes = [note for note in notes if note['id'] != int(note_id)]
    notes_storage.save_notes(notes)
    print('Note deleted successfully.')