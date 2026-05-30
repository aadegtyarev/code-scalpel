import json
import sys

def add(text):
    notes = load_notes()
    notes.append({'id': len(notes) + 1, 'text': text})
    save_notes(notes)

def list_notes():
    notes = load_notes()
    for note in notes:
        print(f"{note['id']}: {note['text']}")

def search_notes(query):
    notes = load_notes()
    results = [note for note in notes if query.lower() in note['text'].lower()]
    for note in results:
        print(f"{note['id']}: {note['text']}")

def delete_note(note_id):
    notes = load_notes()
    notes = [note for note in notes if note['id'] != int(note_id)]
    save_notes(notes)

def load_notes():
    try:
        with open('notes.json', 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_notes(notes):
    with open('notes.json', 'w') as f:
        json.dump(notes, f, indent=4)

if __name__ == "__main__":
    command = sys.argv[1]
    if command == 'add':
        add(sys.argv[2])
    elif command == 'list':
        list_notes()
    elif command == 'search':
        search_notes(sys.argv[2])
    elif command == 'delete':
        delete_note(sys.argv[2])
    else:
        print('Unknown command')