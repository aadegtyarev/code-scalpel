import argparse
from .storage import Storage

def main():
    parser = argparse.ArgumentParser(description='Программа для работы с заметками')
    subparsers = parser.add_subparsers(dest='command')

    # Команда add
    add_parser = subparsers.add_parser('add', help='Добавляет новую заметку')
    add_parser.add_argument('title', type=str, help='Название заметки')
    add_parser.add_argument('content', type=str, help='Текст заметки')

    # Команда list
    list_parser = subparsers.add_parser('list', help='Выводит список всех заметок')

    # Команда search
    search_parser = subparsers.add_parser('search', help='Ищет заметки по названию или тексту')
    search_parser.add_argument('query', type=str, help='Поисковая строка')

    # Команда delete
    delete_parser = subparsers.add_parser('delete', help='Удаляет заметку по её идентификатору')
    delete_parser.add_argument('index', type=int, help='Индекс заметки для удаления')

    args = parser.parse_args()

    storage = Storage()

    if args.command == 'add':
        storage.add(args.title, args.content)
        print(f'Заметка добавлена: {args.title}')
    elif args.command == 'list':
        notes = storage.list()
        for i, note in enumerate(notes):
            print(f'{i}: {note['title']}')
    elif args.command == 'search':
        results = storage.search(args.query)
        if not results:
            print('Ничего не найдено.')
        else:
            for i, note in enumerate(results):
                print(f'{i}: {note['title']}')
    elif args.command == 'delete':
        storage.delete(args.index)
        print(f'Заметка удалена: индекс {args.index}')

if __name__ == '__main__':
    main()