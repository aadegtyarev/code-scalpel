import argparse
from .storage import NoteStorage
def main():
    parser = argparse.ArgumentParser(description='Программа для управления заметками.')
    subparsers = parser.add_subparsers(dest='command')

    # Команда add
    parser_add = subparsers.add_parser('add', help='Добавить новую заметку')
    parser_add.add_argument('note_text', type=str, help='Текст заметки')

    # Команда list
    parser_list = subparsers.add_parser('list', help='Вывести список всех заметок')

    # Команда search
    parser_search = subparsers.add_parser('search', help='Искать заметки по ключевому слову')
    parser_search.add_argument('keyword', type=str, help='Ключевое слово для поиска')

    # Команда delete
    parser_delete = subparsers.add_parser('delete', help='Удалить заметку')
    parser_delete.add_argument('note_id', type=int, help='ID заметки для удаления')

    args = parser.parse_args()

    storage = NoteStorage()

    if args.command == 'add':
        storage.add_note(args.note_text)
        print(f'Заметка добавлена: {args.note_text}')
    elif args.command == 'list':
        notes = storage.list_notes()
        for note in notes:
            print(f'{note['id']} - {note['text']}')
    elif args.command == 'search':
        notes = storage.search_notes(args.keyword)
        for note in notes:
            print(f'{note['id']} - {note['text']}')
    elif args.command == 'delete':
        storage.delete_note(args.note_id)
        print(f'Заметка с ID {args.note_id} удалена.')

if __name__ == '__main__':
    main()