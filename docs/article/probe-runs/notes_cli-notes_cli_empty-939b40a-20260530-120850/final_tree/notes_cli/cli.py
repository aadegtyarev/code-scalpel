import argparse
from notes_cli.storage import JSONStorage

def main():
    parser = argparse.ArgumentParser(description='Notes CLI')
    subparsers = parser.add_subparsers(dest='command')

    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new note')
    add_parser.add_argument('content', type=str, help='Content of the note')

    # List command
    list_parser = subparsers.add_parser('list', help='List all notes')

    # Search command
    search_parser = subparsers.add_parser('search', help='Search notes by content')
    search_parser.add_argument('query', type=str, help='Query string to search for')

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a note by ID')
    delete_parser.add_argument('note_id', type=int, help='ID of the note to delete')

    args = parser.parse_args()

    storage = JSONStorage('notes.json')

    if args.command == 'add':
        new_note = storage.add(args.content)
        print(f'Added: {new_note}')
    elif args.command == 'list':
        notes = storage.get_all()
        for note in notes:
            print(note)
    elif args.command == 'search':
        results = storage.search(args.query)
        for result in results:
            print(result)
    elif args.command == 'delete':
        storage.delete(args.note_id)
        print(f'Deleted note with ID {args.note_id}')

if __name__ == '__main__':
    main()