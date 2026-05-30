import argparse
import json
import os

def add(note):
    notes = load_notes()
    notes.append(note)
    save_notes(notes)
    print(f'Заметка добавлена: {note}')

def list_notes():
    notes = load_notes()
    for i, note in enumerate(notes):
        print(f'{i}: {note}')

def search(query):
    notes = load_notes()
    results = [note for note in notes if query.lower() in note.lower()]
    for i, note in enumerate(results):
        print(f'{i}: {note}')

def delete(index):
    notes = load_notes()
    if 0 <= index < len(notes):
        deleted_note = notes.pop(index)
        save_notes(notes)
        print(f'Заметка удалена: {deleted_note}')
    else:
        print('Неверный индекс')

def load_notes():
    if os.path.exists('notes.json'):
        with open('notes.json', 'r') as f:
            return json.load(f)
    return []

def save_notes(notes):
    with open('notes.json', 'w') as f:
        json.dump(notes, f, indent=4)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CLI для заметок')
    subparsers = parser.add_subparsers(dest='command')

    add_parser = subparsers.add_parser('add', help='Добавить новую заметку')
    add_parser.add_argument('note', type=str, help='Текст заметки')
    add_parser.set_defaults(func=add)

    list_parser = subparsers.add_parser('list', help='Вывести все заметки')
    list_parser.set_defaults(func=list_notes)

    search_parser = subparsers.add_parser('search', help='Искать заметки по ключевому слову')
    search_parser.add_argument('query', type=str, help='Ключевое слово для поиска')
    search_parser.set_defaults(func=search)

    delete_parser = subparsers.add_parser('delete', help='Удалить заметку по её индексу')
    delete_parser.add_argument('index', type=int, help='Индекс заметки')
    delete_parser.set_defaults(func=delete)

    args = parser.parse_args()
    if args.command:
        args.func(args)