import argparse
import json
import os

def add_note(note):
    notes = load_notes()
    notes.append(note)
    save_notes(notes)

def list_notes():
    notes = load_notes()
    return '\n'.join(notes)

def search_notes(query):
    notes = load_notes()
    results = [note for note in notes if query.lower() in note.lower()]
    return '\n'.join(results)

def delete_note(index):
    notes = load_notes()
    if 0 <= index < len(notes):
        del notes[index]
        save_notes(notes)
    else:
        print('Invalid index')

def load_notes():
    if os.path.exists('notes.json'):
        with open('notes.json', 'r') as f:
            return json.load(f)
    else:
        return []

def save_notes(notes):
    with open('notes.json', 'w') as f:
        json.dump(notes, f)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Notes CLI tool.')
    subparsers = parser.add_subparsers(dest='command')

    add_parser = subparsers.add_parser('add', help='Add a new note')
    add_parser.add_argument('note', type=str, help='The note to add')

    list_parser = subparsers.add_parser('list', help='List all notes')

    search_parser = subparsers.add_parser('search', help='Search for notes by query')
    search_parser.add_argument('query', type=str, help='The search query')

    delete_parser = subparsers.add_parser('delete', help='Delete a note by index')
    delete_parser.add_argument('index', type=int, help='The index of the note to delete')

    args = parser.parse_args()

    if args.command == 'add':
        add_note(args.note)
    elif args.command == 'list':
        print(list_notes())
    elif args.command == 'search':
        print(search_notes(args.query))
    elif args.command == 'delete':
        delete_note(args.index)