import argparse
from .storage import Storage

def main():
    parser = argparse.ArgumentParser(description='CLI для заметок')
    subparsers = parser.add_subparsers(dest='command', help='Доступные команды')

    # Команда add
    add_parser = subparsers.add_parser('add', help='Добавить новую заметку')
    add_parser.add_argument('note', type=str, help='Текст заметки')

    # Команда list
    list_parser = subparsers.add_parser('list', help='Вывести список всех заметок')

    # Команда search
    search_parser = subparsers.add_parser('search', help='Искать заметки по ключевым словам')
    search_parser.add_argument('keyword', type=str, help='Ключевое слово для поиска')

    # Команда delete
    delete_parser = subparsers.add_parser('delete', help='Удалить заметку по её индексу')
    delete_parser.add_argument('index', type=int, help='Индекс заметки для удаления')

    args = parser.parse_args()

    storage = Storage()

    if args.command == 'add':
        storage.add(args.note)
    elif args.command == 'list':
        notes = storage.list()
        for i, note in enumerate(notes):
            print(f'{i}: {note}')
    elif args.command == 'search':
        results = storage.search(args.keyword)
        for i, note in enumerate(results):
            print(f'{i}: {note}')
    elif args.command == 'delete':
        storage.delete(args.index)

if __name__ == '__main__':
    main()
