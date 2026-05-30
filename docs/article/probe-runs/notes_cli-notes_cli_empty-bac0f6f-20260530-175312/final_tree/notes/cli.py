import argparse
from notes.storage import Storage

def main():
    parser = argparse.ArgumentParser(description='Программа для управления заметками.')
    subparsers = parser.add_subparsers(dest='command')

    # Команда add
    add_parser = subparsers.add_parser('add', help='Добавить новую заметку.')
    add_parser.add_argument('note', type=str, help='Текст заметки.')
    add_parser.set_defaults(func=add_note)

    # Команда list
    list_parser = subparsers.add_parser('list', help='Вывести список всех заметок.')
    list_parser.set_defaults(func=list_notes)

    # Команда search
    search_parser = subparsers.add_parser('search', help='Искать заметки по ключевому слову.')
    search_parser.add_argument('keyword', type=str, help='Ключевое слово для поиска.')
    search_parser.set_defaults(func=search_notes)

    # Команда delete
    delete_parser = subparsers.add_parser('delete', help='Удалить заметку по идентификатору.')
    delete_parser.add_argument('index', type=int, help='Индекс заметки для удаления.')
    delete_parser.set_defaults(func=delete_note)

    args = parser.parse_args()
    if args.command == 'add':
        storage = Storage()
        storage.add(args.note)
        print(f'Заметка добавлена: {args.note}')
    elif args.command == 'list':
        storage = Storage()
        notes = storage.list()
        for note in notes:
            print(note)
    elif args.command == 'search':
        storage = Storage()
        results = storage.search(args.keyword)
        if results:
            for result in results:
                print(result)
        else:
            print('Ничего не найдено.')
    elif args.command == 'delete':
        storage = Storage()
        storage.delete(args.index)
        print(f'Заметка удалена: {args.index}')


def add_note(args):
    storage = Storage()
    storage.add(args.note)
    print(f'Заметка добавлена: {args.note}')

def list_notes(args):
    storage = Storage()
    notes = storage.list()
    for note in notes:
        print(note)

def search_notes(args):
    storage = Storage()
    results = storage.search(args.keyword)
    if results:
        for result in results:
            print(result)
    else:
        print('Ничего не найдено.')

def delete_note(args):
    storage = Storage()
    storage.delete(args.index)
    print(f'Заметка удалена: {args.index}')