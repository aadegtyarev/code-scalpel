import argparse
import json
import os

def add(text):
    notes = load_notes()
    notes.append(text)
    save_notes(notes)

def list_notes():
    notes = load_notes()
    for i, note in enumerate(notes, start=1):
        print(f'{i}: {note}')

def search(query):
    notes = load_notes()
    results = [note for note in notes if query.lower() in note.lower()]
    for i, result in enumerate(results, start=1):
        print(f'{i}: {result}')

def delete(index):
    notes = load_notes()
    if 0 < index <= len(notes):
        del notes[index - 1]
        save_notes(notes)
    else:
        print('Неверный индекс')

def load_notes():
    if os.path.exists('notes.json'):
        with open('notes.json', 'r') as file:
            return json.load(file)
    return []

def save_notes(notes):
    with open('notes.json', 'w') as file:
        json.dump(notes, file)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CLI для заметок')
    subparsers = parser.add_subparsers(dest='command')

    add_parser = subparsers.add_parser('add', help='Добавляет новую заметку')
    add_parser.add_argument('text', type=str, help='Текст заметки')

    list_parser = subparsers.add_parser('list', help='Выводит все сохраненные заметки')

    search_parser = subparsers.add_parser('search', help='Ищет заметки по ключевым словам')
    search_parser.add_argument('query', type=str, help='Ключевые слова для поиска')

    delete_parser = subparsers.add_parser('delete', help='Удаляет заметку по идентификатору')
    delete_parser.add_argument('index', type=int, help='Индекс заметки')

    args = parser.parse_args()

    if args.command == 'add':
        add(args.text)
    elif args.command == 'list':
        list_notes()
    elif args.command == 'search':
        search(args.query)
    elif args.command == 'delete':
        delete(args.index)