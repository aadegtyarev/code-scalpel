import argparse
import json
import os

def add_note(note):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        with open(notes_path, 'w') as f:
            json.dump([], f)
    with open(notes_path, 'r+') as f:
        notes = json.load(f)
        notes.append(note)
        f.seek(0)
        json.dump(notes, f, indent=4)

def list_notes():
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        print('No notes found.')
        return
    with open(notes_path, 'r') as f:
        notes = json.load(f)
    for i, note in enumerate(notes, start=1):
        print(f'{i}. {note}')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Notes CLI')
    subparsers = parser.add_subparsers(dest='command')
    
    add_parser = subparsers.add_parser('add', help='Add a new note')
    add_parser.add_argument('note', type=str, help='Note text')
    add_parser.set_defaults(func=add_note)
    
    list_parser = subparsers.add_parser('list', help='List all notes')
    list_parser.set_defaults(func=list_notes)
    
    args = parser.parse_args()
    if args.func:
        args.func()