import argparse
from notes.storage import Storage

def main(args=None):
    parser = argparse.ArgumentParser(description='CLI for managing notes.')
    subparsers = parser.add_subparsers(dest='command')
    
    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new note.')
    add_parser.add_argument('note', type=str, help='The content of the note.')
    
    # List command
    list_parser = subparsers.add_parser('list', help='List all notes.')
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Search for a note.')
    search_parser.add_argument('query', type=str, help='Query to search for.')
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a note by index.')
    delete_parser.add_argument('index', type=int, help='Index of the note to delete.')
    
    if args is None:
        args = parser.parse_args()
    else:
        args = parser.parse_args(args)
    
    storage = Storage()
    if args.command == 'add':
        storage.add_note(args.note)
    elif args.command == 'list':
        for note in storage.notes:
            print(note)
    elif args.command == 'search':
        results = storage.search_notes(args.query)
        for result in results:
            print(result)
    elif args.command == 'delete':
        storage.delete_note(args.index)

if __name__ == '__main__':
    main()