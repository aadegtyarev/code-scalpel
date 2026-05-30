import argparse
from .notes import add_note, list_notes, search_notes, delete_note
def main(args=None):
    parser = argparse.ArgumentParser(description='CLI для заметок')
    subparsers = parser.add_subparsers(dest='command', required=True)

    # Команда add
    add_parser = subparsers.add_parser('add', help='Добавляет новую заметку')
    add_parser.add_argument('text', type=str, help='Текст заметки')
    add_parser.set_defaults(func=add_note)

    # Команда list
    list_parser = subparsers.add_parser('list', help='Выводит список всех заметок')
    list_parser.set_defaults(func=list_notes)

    # Команда search
    search_parser = subparsers.add_parser('search', help='Ищет заметки по ключевому слову')
    search_parser.add_argument('keyword', type=str, help='Ключевое слово для поиска')
    search_parser.set_defaults(func=search_notes)

    # Команда delete
    delete_parser = subparsers.add_parser('delete', help='Удаляет заметку по её индексу в списке')
    delete_parser.add_argument('index', type=int, help='Индекс заметки для удаления')
    delete_parser.set_defaults(func=delete_note)

    if args is None:
        args = parser.parse_args()
    result = args.func(args.text if 'text' in args else args.keyword if 'keyword' in args else args.index)
    if isinstance(result, list):
        for note in result:
            print(note)
    else:
        print('Заметка добавлена')

if __name__ == '__main__':
    main()