import argparse
from .storage import add_note, list_notes, search_notes, delete_note

def main():
    parser = argparse.ArgumentParser(description='Notes CLI')
    subparsers = parser.add_subparsers(dest='command', help='Available commands')

    # Add command
    add_parser = subparsers.add_parser('add', help='Add a new note')
    add_parser.add_argument('text', type=str, help='Note text')
    add_parser.set_defaults(func=add_note)

    # List command
    list_parser = subparsers.add_parser('list', help='List all notes')
    list_parser.set_defaults(func=list_notes)

    # Search command
    search_parser = subparsers.add_parser('search', help='Search notes by keyword')
    search_parser.add_argument('keyword', type=str, help='Keyword to search for')
    search_parser.set_defaults(func=search_notes)

    # Delete command
    delete_parser = subparsers.add_parser('delete', help='Delete a note by index')
    delete_parser.add_argument('index', type=int, help='Index of the note to delete')
    delete_parser.set_defaults(func=delete_note)

    args = parser.parse_args()
    if args.command:
        args.func(args)
    else:
        parser.print_help()
