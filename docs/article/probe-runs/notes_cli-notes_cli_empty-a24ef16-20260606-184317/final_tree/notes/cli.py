import argparse
from notes.storage import Storage

def main(argv=None):
    parser = argparse.ArgumentParser(description="CLI для управления заметками")
    subparsers = parser.add_subparsers(dest='command')
    
    # Команда add
    add_parser = subparsers.add_parser('add', help='Добавить новую заметку')
    add_parser.add_argument('text', type=str, help='Текст заметки')
    
    # Команда list
    list_parser = subparsers.add_parser('list', help='Вывести список всех заметок')
    
    # Команда search
    search_parser = subparsers.add_parser('search', help='Ищет заметки по ключевому слову')
    search_parser.add_argument('keyword', type=str, help='Ключевое слово для поиска')
    
    # Команда delete
    delete_parser = subparsers.add_parser('delete', help='Удаляет заметку по её индексу')
    delete_parser.add_argument('index', type=int, help='Индекс заметки для удаления')
    
    args = parser.parse_args(argv)
    storage = Storage()
    
    if args.command == 'add':
        storage.add_note(args.text)
    elif args.command == 'list':
        notes = storage.list_notes()
        for i, note in enumerate(notes):
            print(f'{i}: {note}')
    elif args.command == 'search':
        results = storage.search_notes(args.keyword)
        for i, note in enumerate(results):
            print(f'{i}: {note}')
    elif args.command == 'delete':
        storage.delete_note(args.index)
