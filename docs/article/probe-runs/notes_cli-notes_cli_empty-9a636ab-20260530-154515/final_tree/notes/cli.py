import json
import sys
import os
from argparse import ArgumentParser

def main(args, storage_path='notes.json'):
    if not os.path.exists(storage_path):
        with open(storage_path, 'w') as f:
            json.dump([], f)
    
    with open(storage_path, 'r') as f:
        notes = json.load(f)
    
    parser = ArgumentParser(description='Notes CLI')
    subparsers = parser.add_subparsers(dest='command')
    
    add_parser = subparsers.add_parser('add', help='Add a new note')
    add_parser.add_argument('text', help='Note text')
    
    list_parser = subparsers.add_parser('list', help='List all notes')
    
    search_parser = subparsers.add_parser('search', help='Search notes by keyword')
    search_parser.add_argument('keyword', help='Keyword to search for')
    
    delete_parser = subparsers.add_parser('delete', help='Delete a note by index')
    delete_parser.add_argument('index', type=int, help='Index of the note to delete')
    
    args = parser.parse_args(args)
    
    if args.command == 'add':
        notes.append({'text': args.text})
        with open(storage_path, 'w') as f:
            json.dump(notes, f)
        return 0
    elif args.command == 'list':
        for i, note in enumerate(notes):
            print(f'{i}: {note['text']}')
        return 0
    elif args.command == 'search':
        results = [note for note in notes if args.keyword.lower() in note['text'].lower()]
        for i, result in enumerate(results):
            print(f'{i}: {result['text']}')
        return 0
    elif args.command == 'delete':
        if 0 <= args.index < len(notes):
            del notes[args.index]
            with open(storage_path, 'w') as f:
                json.dump(notes, f)
            return 0
        else:
            print('Invalid index')
            return 1
    else:
        parser.print_help()
        return 1