import json
import os

def _load_notes():
    if not os.path.exists("notes.json"):
        return []
    with open("notes.json", "r") as f:
        return json.load(f)

def _save_notes(notes):
    with open("notes.json", "w") as f:
        json.dump(notes, f, indent=4)

def add_note(note):
    notes = _load_notes()
    notes.append(note)
    _save_notes(notes)

def list_notes():
    return _load_notes()

def search_notes(query):
    notes = _load_notes()
    return [note for note in notes if query.lower() in note.lower()]

def delete_note(index):
    notes = _load_notes()
    if 0 <= index < len(notes):
        del notes[index]
        _save_notes(notes)
    else:
        raise IndexError("Некорректный индекс заметки")