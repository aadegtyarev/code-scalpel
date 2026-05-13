import argparse

def main():
    parser = argparse.ArgumentParser(description='CLI для заметок')
    subparsers = parser.add_subparsers(dest='command', help='Доступные команды')

    # Команда add
    parser_add = subparsers.add_parser('add', help='Добавить новую заметку')
    parser_add.add_argument('note_text', type=str, help='Текст заметки')

    # Команда list
    parser_list = subparsers.add_parser('list', help='Вывести все заметки')

    # Команда search
    parser_search = subparsers.add_parser('search', help='Поиск заметок по ключевому слову')
    parser_search.add_argument('keyword', type=str, help='Ключевое слово для поиска')

    # Команда delete
    parser_delete = subparsers.add_parser('delete', help='Удалить заметку по идентификатору')
    parser_delete.add_argument('note_id', type=int, help='Идентификатор заметки')

    args = parser.parse_args()

    if args.command == 'add':
        print(f'Добавлена новая заметка: {args.note_text}')
    elif args.command == 'list':
        print('Вывод всех заметок')
    elif args.command == 'search':
        print(f'Поиск заметок по ключевому слову: {args.keyword}')
    elif args.command == 'delete':
        print(f'Удалена заметка с идентификатором: {args.note_id}')

if __name__ == '__main__':
    main()