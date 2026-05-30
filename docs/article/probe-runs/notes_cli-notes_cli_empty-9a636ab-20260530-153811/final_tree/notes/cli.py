import argparse
import json
import os

NOTES_FILE = 'notes.json'

def load_notes():
    if not os.path.exists(NOTES_FILE):
        return []
    with open(NOTES_FILE, 'r') as f:
        return json.load(f)

def save_notes(notes):
    with open(NOTES_FILE, 'w') as f:
        json.dump(notes, f, indent=4)

def add_note(note):
    notes = load_notes()
    notes.append(note)
    save_notes(notes)
    print(f'Note added: {note}')

def list_notes():
    notes = load_notes()
    if not notes:
        print('No notes found.')
    else:
        for index, note in enumerate(notes):
            print(f'{index + 1}: {note}')

def search_notes(query):
    notes = load_notes()
    results = [note for note in notes if query.lower() in note.lower()]
    if not results:
        print('No matching notes found.')
    else:
        for index, note in enumerate(results):
            print(f'{index + 1}: {note}')

def delete_note(index):
    notes = load_notes()
    if 0 <= index < len(notes):
        deleted_note = notes.pop(index)
        save_notes(notes)
        print(f'Note deleted: {deleted_note}')
    else:
        print('Invalid note index.')

def main():
    parser = argparse.ArgumentParser(description='Notes CLI')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new note')
    add_parser.add_argument('note', type=str, help='The note to add')

    # List command
    list_parser = subparsers.add_parser('list', help='List all notes')

    # Search command
    search_parser = subparsers.add_parser('search', help='Search notes by keyword')
    search_parser.add_argument('query', type=str, help='The keyword to search for')

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a note by index')
    delete_parser.add_argument('index', type=int, help='The index of the note to delete')

    args = parser.parse_args()

    if args.command == 'add':
        add_note(args.note)
    elif args.command == 'list':
        list_notes()
    elif args.command == 'search':
        search_notes(args.query)
    elif args.command == 'delete':
        delete_note(args.index - 1)  # Convert to 0-based index
    else:
        parser.print_help()

if __name__ == '__main__':
    main()