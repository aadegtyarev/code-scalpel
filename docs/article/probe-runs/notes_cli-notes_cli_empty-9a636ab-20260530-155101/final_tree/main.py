import argparse
from storage import NoteStorage

def add_note(storage, text):
    storage.add_note(text)
    print(f'Заметка добавлена: {text}')

def list_notes(storage):
    notes = storage.list_notes()
    if not notes:
        print('Нет заметок.')
    else:
        for note in notes:
            print(f'{note['id']}: {note['text']}')

def search_notes(storage, query):
    results = storage.search_notes(query)
    if not results:
        print('Ничего не найдено.')
    else:
        for note in results:
            print(f'{note['id']}: {note['text']}')

def delete_note(storage, note_id):
    try:
        storage.delete_note(note_id)
        print(f'Заметка с ID {note_id} удалена.')
    except ValueError as e:
        print(e)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Программа для заметок')
    subparsers = parser.add_subparsers(dest='command', help='Доступные команды')

    add_parser = subparsers.add_parser('add', help='Добавить новую заметку')
    add_parser.add_argument('text', type=str, help='Текст заметки')

    list_parser = subparsers.add_parser('list', help='Показать все заметки')

    search_parser = subparsers.add_parser('search', help='Найти заметки по тексту')
    search_parser.add_argument('query', type=str, help='Текст для поиска')

    delete_parser = subparsers.add_parser('delete', help='Удалить заметку по ID')
    delete_parser.add_argument('note_id', type=int, help='ID заметки')

    args = parser.parse_args()

    storage = NoteStorage()

    if args.command == 'add':
        add_note(storage, args.text)
    elif args.command == 'list':
        list_notes(storage)
    elif args.command == 'search':
        search_notes(storage, args.query)
    elif args.command == 'delete':
        delete_note(storage, args.note_id)
