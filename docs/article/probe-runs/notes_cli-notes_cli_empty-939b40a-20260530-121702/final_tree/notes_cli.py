import argparse
import json
from storage import add_note, get_notes, search_notes, delete_note

def main():
    parser = argparse.ArgumentParser(description='Программа для работы с заметками')
    subparsers = parser.add_subparsers(dest='command', help='Доступные команды')

    # Команда add
    parser_add = subparsers.add_parser('add', help='Добавить новую заметку')
    parser_add.add_argument('note', type=str, help='Текст заметки')
    parser_add.set_defaults(func=add_note)

    # Команда list
    parser_list = subparsers.add_parser('list', help='Вывести список всех заметок')
    parser_list.set_defaults(func=get_notes)

    # Команда search
    parser_search = subparsers.add_parser('search', help='Найти заметки по ключевому слову')
    parser_search.add_argument('keyword', type=str, help='Ключевое слово для поиска')
    parser_search.set_defaults(func=search_notes)

    # Команда delete
    parser_delete = subparsers.add_parser('delete', help='Удалить заметку по её номеру')
    parser_delete.add_argument('index', type=int, help='Номер заметки для удаления')
    parser_delete.set_defaults(func=delete_note)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
    else:
        args.func(args.note) if args.command == 'add' else args.func(args.index) if args.command == 'delete' else args.func(args.keyword) if args.command == 'search' else args.func()

if __name__ == '__main__':
    main()