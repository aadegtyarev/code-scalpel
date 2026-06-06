import sys
from notes import add, list_notes, search, delete

def main(argv=None):
    if argv is None:
        argv = sys.argv
    if len(argv) < 2:
        print('Usage: python main.py [add|list|search|delete] [args]')
        sys.exit(1)
    command = argv[1]
    if command == 'add':
        if len(argv) < 3:
            print('Usage: python main.py add "note text"')
            sys.exit(1)
        note_id = add(' '.join(argv[2:]))
        print(f'Note added with ID {note_id}')
        sys.exit(0)
    elif command == 'list':
        notes = list_notes()
        for note in notes:
            print(f'{note['id']}: {note['text']}')
        sys.exit(0)
    elif command == 'search':
        if len(argv) < 3:
            print('Usage: python main.py search "query"')
            sys.exit(1)
        results = search(' '.join(argv[2:]))
        for result in results:
            print(f'{result['id']}: {result['text']}')
        sys.exit(0)
    elif command == 'delete':
        if len(argv) < 3:
            print('Usage: python main.py delete <note_id>')
            sys.exit(1)
        note_id = int(argv[2])
        if delete(note_id):
            print(f'Note with ID {note_id} deleted')
        else:
            print(f'Note with ID {note_id} not found')
        sys.exit(0)
    else:
        print('Unknown command')
        sys.exit(1)

if __name__ == '__main__':
    main()