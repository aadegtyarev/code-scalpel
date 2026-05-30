#!/usr/bin/env python

def main():
    import argparse
    parser = argparse.ArgumentParser(description='Программа для заметок')
    subparsers = parser.add_subparsers(dest='command')

    # Команда add
    add_parser = subparsers.add_parser('add', help='Добавить новую заметку')
    add_parser.add_argument('text', type=str, help='Текст заметки')

    # Команда list
    list_parser = subparsers.add_parser('list', help='Вывести все сохраненные заметки')

    # Команда search
    search_parser = subparsers.add_parser('search', help='Искать заметки по тексту')
    search_parser.add_argument('query', type=str, help='Текст для поиска')

    # Команда delete
    delete_parser = subparsers.add_parser('delete', help='Удалить заметку по её индексу или идентификатору')
    delete_parser.add_argument('index', type=int, help='Индекс заметки для удаления')

    args = parser.parse_args()

    if args.command == 'add':
        from notes.storage import add_note
        add_note(args.text)
    elif args.command == 'list':
        from notes.storage import list_notes
        print(list_notes())
    elif args.command == 'search':
        from notes.storage import search_notes
        print(search_notes(args.query))
    elif args.command == 'delete':
        from notes.storage import delete_note
        delete_note(args.index)

if __name__ == '__main__':
    main()