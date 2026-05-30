import json
import sys
from pathlib import Path

def add_note(text):
    notes_path = Path('notes/notes.json')
    if not notes_path.exists():
        notes = []
    else:
        with open(notes_path, 'r') as f:
            notes = json.load(f)
    new_note = {
        'id': len(notes) + 1,
        'text': text
    }
    notes.append(new_note)
    with open(notes_path, 'w') as f:
        json.dump(notes, f, indent=4)

def list_notes():
    notes_path = Path('notes/notes.json')
    if not notes_path.exists():
        print("Нет заметок")
        return
    with open(notes_path, 'r') as f:
        notes = json.load(f)
    for note in notes:
        print(f"{note['id']}: {note['text']}")

def search_notes(query):
    notes_path = Path('notes/notes.json')
    if not notes_path.exists():
        print("Нет заметок")
        return
    with open(notes_path, 'r') as f:
        notes = json.load(f)
    for note in notes:
        if query.lower() in note['text'].lower():
            print(f"{note['id']}: {note['text']}")

def delete_note(note_id):
    notes_path = Path('notes/notes.json')
    if not notes_path.exists():
        print("Нет заметок")
        return
    with open(notes_path, 'r') as f:
        notes = json.load(f)
    notes = [note for note in notes if note['id'] != int(note_id)]
    with open(notes_path, 'w') as f:
        json.dump(notes, f, indent=4)

if __name__ == '__main__':
    command = sys.argv[1] if len(sys.argv) > 1 else None
    if command == 'add':
        text = ' '.join(sys.argv[2:])
        add_note(text)
    elif command == 'list':
        list_notes()
    elif command == 'search':
        query = ' '.join(sys.argv[2:])
        search_notes(query)
    elif command == 'delete':
        note_id = sys.argv[2] if len(sys.argv) > 2 else None
        delete_note(note_id)
    else:
        print("Неизвестная команда")