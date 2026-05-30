import argparse
from notes.storage import NoteStorage

def add_note(note):
    storage = NoteStorage()
    notes = storage.load_notes()
    notes.append(note)
    storage.save_notes(notes)
    print(f"Note added: {note}")

def list_notes():
    storage = NoteStorage()
    notes = storage.load_notes()
    if not notes:
        print("No notes found.")
    else:
        for i, note in enumerate(notes):
            print(f"{i}: {note}")

def search_notes(query):
    storage = NoteStorage()
    notes = storage.load_notes()
    results = [note for note in notes if query.lower() in note.lower()]
    if not results:
        print("No matching notes found.")
    else:
        for i, note in enumerate(results):
            print(f"{i}: {note}")

def delete_note(index):
    storage = NoteStorage()
    notes = storage.load_notes()
    if 0 <= index < len(notes):
        del notes[index]
        storage.save_notes(notes)
        print(f"Note deleted: {notes[index]}")
    else:
        print("Invalid note index.")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Notes CLI")
    subparsers = parser.add_subparsers(dest='command')

    add_parser = subparsers.add_parser('add', help='Add a new note')
    add_parser.add_argument('note', type=str, help='Note text')
    add_parser.set_defaults(func=add_note)

    list_parser = subparsers.add_parser('list', help='List all notes')
    list_parser.set_defaults(func=list_notes)

    search_parser = subparsers.add_parser('search', help='Search for notes')
    search_parser.add_argument('query', type=str, help='Search query')
    search_parser.set_defaults(func=search_notes)

    delete_parser = subparsers.add_parser('delete', help='Delete a note by index')
    delete_parser.add_argument('index', type=int, help='Note index')
    delete_parser.set_defaults(func=delete_note)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args.note) if hasattr(args, 'note') else args.func(args.query) if hasattr(args, 'query') else args.func(args.index)