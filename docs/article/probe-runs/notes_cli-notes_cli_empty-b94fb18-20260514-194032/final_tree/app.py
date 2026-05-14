#!/usr/bin/env python
import argparse
import json
from storage import NoteStorage

def main():
    parser = argparse.ArgumentParser(description='CLI for managing notes.')
    subparsers = parser.add_subparsers(dest='command')
    
    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new note.')
    add_parser.add_argument('note', type=str, help='The content of the note.')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List all notes.')
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Search for a note by keyword.')
    search_parser.add_argument('keyword', type=str, help='The keyword to search for.')
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a note by index.')
    delete_parser.add_argument('index', type=int, help='The index of the note to delete.')
    
    args = parser.parse_args()
    storage = NoteStorage()
    
    if args.command == 'add':
        storage.add_note(args.note)
    elif args.command == 'list':
        notes = storage.list_notes()
        for i, note in enumerate(notes):
            print(f'{i}: {note}')
    elif args.command == 'search':
        results = storage.search_notes(args.keyword)
        for i, result in enumerate(results):
            print(f'{i}: {result}')
    elif args.command == 'delete':
        storage.delete_note(args.index)

if __name__ == '__main__':
    main()