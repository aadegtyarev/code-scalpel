#!/usr/bin/env python3
import argparse
import json
import os

def load_notes():
    if not os.path.exists('storage.json'):
        return []
    with open('storage.json', 'r') as f:
        return json.load(f)

def save_notes(notes):
    with open('storage.json', 'w') as f:
        json.dump(notes, f, indent=4)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CLI for notes.')
    subparsers = parser.add_subparsers(dest='command')

    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new note.')
    add_parser.add_argument('note', type=str, help='Note text.')

    # List command
    list_parser = subparsers.add_parser('list', help='List all notes.')

    # Search command
    search_parser = subparsers.add_parser('search', help='Search notes by keyword.')
    search_parser.add_argument('keyword', type=str, help='Keyword to search for.')

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a note by index.')
    delete_parser.add_argument('index', type=int, help='Index of the note to delete.')

    args = parser.parse_args()

    notes = load_notes()

    if args.command == 'add':
        notes.append(args.note)
        save_notes(notes)
        print(f'Note added: {args.note}')
    elif args.command == 'list':
        for i, note in enumerate(notes):
            print(f'{i}: {note}')
    elif args.command == 'search':
        results = [note for note in notes if args.keyword.lower() in note.lower()]
        for i, note in enumerate(results):
            print(f'{i}: {note}')
    elif args.command == 'delete':
        if 0 <= args.index < len(notes):
            del notes[args.index]
            save_notes(notes)
            print(f'Note deleted at index {args.index}')
        else:
            print('Invalid index.')