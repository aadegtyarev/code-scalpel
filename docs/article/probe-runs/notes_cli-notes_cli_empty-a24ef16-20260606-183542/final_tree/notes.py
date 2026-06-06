import json
import sys

def add_note(text):
    notes = load_notes()
    notes.append({'id': len(notes) + 1, 'text': text})
    save_notes(notes)

def list_notes():
    notes = load_notes()
    for note in notes:
        print(f'{note['id']}: {note['text']}')

def search_notes(query):
    notes = load_notes()
    results = [note for note in notes if query.lower() in note['text'].lower()]
    for note in results:
        print(f'{note['id']}: {note['text']}')

def main(argv=None):
    if argv is None:
        argv = sys.argv
    if len(argv) < 2:
        print('Usage: python notes.py [add|list|search] [text]')
        return 1
    command = argv[1]
    if command == 'add':
        if len(argv) < 3:
            print('Usage: python notes.py add [text]')
            return 1
        text = ' '.join(argv[2:])
        add_note(text)
    elif command == 'list':
        list_notes()
    elif command == 'search':
        if len(argv) < 3:
            print('Usage: python notes.py search [query]')
            return 1
        query = ' '.join(argv[2:])
        search_notes(query)
    else:
        print(f'Unknown command: {command}')
        return 1
    return 0

def load_notes():
    try:
        with open('notes.json', 'r') as file:
            return json.load(file)
    except FileNotFoundError:
        return []

def save_notes(notes):
    with open('notes.json', 'w') as file:
        json.dump(notes, file, indent=4)

if __name__ == '__main__':
    sys.exit(main())