import argparse
from notes import add, list_notes, search, delete

def main(argv=None):
    parser = argparse.ArgumentParser(description='CLI for managing notes.')
    subparsers = parser.add_subparsers(dest='command')
    
    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new note.')
    add_parser.add_argument('note', type=str, help='The note to add.')
    add_parser.set_defaults(func=add)
    
    # List command
    list_parser = subparsers.add_parser('list', help='List all notes.')
    list_parser.set_defaults(func=list_notes)
    
    # Search command
    search_parser = subparsers.add_parser('search', help='Search for a note by query.')
    search_parser.add_argument('query', type=str, help='The query to search for.')
    search_parser.set_defaults(func=search)
    
    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a note by index.')
    delete_parser.add_argument('index', type=int, help='The index of the note to delete.')
    delete_parser.set_defaults(func=delete)
    
    args = parser.parse_args(argv)
    if args.command is None:
        parser.print_help()
    else:
        result = args.func(args.note if 'note' in vars(args) else args.query if 'query' in vars(args) else args.index)
        if isinstance(result, list):
            for note in result:
                print(note)
        elif result is not None:
            print(result)

if __name__ == '__main__':
    main()