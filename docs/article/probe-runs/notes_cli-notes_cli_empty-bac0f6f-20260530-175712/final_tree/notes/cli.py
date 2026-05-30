import argparse
import json
import os

def add_note(note_text):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        with open(notes_path, 'w') as f:
            json.dump([], f)
    with open(notes_path, 'r+') as f:
        notes = json.load(f)
        notes.append(note_text)
        f.seek(0)
        json.dump(notes, f)
        f.truncate()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Notes CLI')
    subparsers = parser.add_subparsers(dest='command')
    
    add_parser = subparsers.add_parser('add', help='Add a new note')
    add_parser.add_argument('note_text', type=str, help='Text of the note to add')
    add_parser.set_defaults(func=add_note)
    
    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args.note_text)