import json
import sys

def add(text):
    with open('notes.json', 'r') as file:
        notes = json.load(file)
    note_id = len(notes) + 1 if notes else 1
    notes.append({'id': note_id, 'text': text})
    with open('notes.json', 'w') as file:
        json.dump(notes, file, indent=4)

def list_notes():
    with open('notes.json', 'r') as file:
        notes = json.load(file)
    for note in notes:
        print(f"{note['id']}: {note['text']}")

if __name__ == "__main__":
    command = sys.argv[1]
    if command == 'add':
        add(sys.argv[2])
    elif command == 'list':
        list_notes()