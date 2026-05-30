import argparse
from notes.storage import Storage

def main():
    parser = argparse.ArgumentParser(description='Notes CLI')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new note')
    add_parser.add_argument('text', type=str, help='Text of the note')

    # List command
    list_parser = subparsers.add_parser('list', help='List all notes')

    # Search command
    search_parser = subparsers.add_parser('search', help='Search for notes containing a keyword')
    search_parser.add_argument('keyword', type=str, help='Keyword to search for')

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a note by ID')
    delete_parser.add_argument('note_id', type=int, help='ID of the note to delete')

    args = parser.parse_args()

    storage = Storage()

    if args.command == 'add':
        note_id = storage.add(args.text)
        print(f'Note added with ID: {note_id}')
    elif args.command == 'list':
        notes = storage.list()
        for note in notes:
            print(f'{note['id']}: {note['text']}')
    elif args.command == 'search':
        results = storage.search(args.keyword)
        if results:
            for result in results:
                print(f'{result['id']}: {result['text']}')
        else:
            print('No notes found containing the keyword.')
    elif args.command == 'delete':
        storage.delete(args.note_id)
        print(f'Note with ID {args.note_id} deleted.')

if __name__ == '__main__':
    main()