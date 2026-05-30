import argparse
from src.notes import Notes, JsonStorage
def main():
    parser = argparse.ArgumentParser(description='Программа для работы с заметками')
    parser.add_argument('command', choices=['add', 'list', 'search', 'delete'])
    parser.add_argument('--text', help='Текст заметки (для команды add)')
    parser.add_argument('--keyword', help='Ключевое слово для поиска (для команды search)')
    parser.add_argument('--index', type=int, help='Индекс заметки (для команды delete)')

    args = parser.parse_args()

    storage = JsonStorage('notes.json')
    notes = Notes(storage)

    if args.command == 'add':
        if args.text:
            notes.add(args.text)
            print(f'Заметка добавлена: {args.text}')
        else:
            print('Укажите текст заметки с помощью --text')
    elif args.command == 'list':
        note_list = notes.list()
        if note_list:
            for i, note in enumerate(note_list):
                print(f'{i}: {note}')
        else:
            print('Нет заметок.')
    elif args.command == 'search':
        if args.keyword:
            search_results = notes.search(args.keyword)
            if search_results:
                for i, note in enumerate(search_results):
                    print(f'{i}: {note}')
            else:
                print('Нет совпадений.')
        else:
            print('Укажите ключевое слово с помощью --keyword')
    elif args.command == 'delete':
        if args.index is not None:
            notes.delete(args.index)
            print(f'Заметка под индексом {args.index} удалена.')
        else:
            print('Укажите индекс заметки с помощью --index')

if __name__ == '__main__':
    main()