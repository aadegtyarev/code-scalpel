import argparse
import json
import os

def add_note(text):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        with open(notes_path, 'w') as f:
            json.dump([], f)
    with open(notes_path, 'r+') as f:
        notes = json.load(f)
        notes.append(text)
        f.seek(0)
        json.dump(notes, f)
        f.truncate()

def list_notes():
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        print('Нет заметок.')
        return
    with open(notes_path, 'r') as f:
        notes = json.load(f)
        for i, note in enumerate(notes, start=1):
            print(f'{i}. {note}')

def search_notes(keyword):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        print('Нет заметок.')
        return
    with open(notes_path, 'r') as f:
        notes = json.load(f)
        found_notes = [note for note in notes if keyword.lower() in note.lower()]
        if not found_notes:
            print('Заметки не найдены.')
            return
        for i, note in enumerate(found_notes, start=1):
            print(f'{i}. {note}')

def delete_note(index):
    notes_path = 'notes.json'
    if not os.path.exists(notes_path):
        print('Нет заметок.')
        return
    with open(notes_path, 'r+') as f:
        notes = json.load(f)
        if 1 <= index <= len(notes):
            del notes[index - 1]
            f.seek(0)
            json.dump(notes, f)
            f.truncate()
            print('Заметка удалена.')
        else:
            print('Неверный индекс заметки.')

def main():
    parser = argparse.ArgumentParser(description='CLI для управления заметками.')
    subparsers = parser.add_subparsers(dest='command')

    add_parser = subparsers.add_parser('add', help='Добавить новую заметку.')
    add_parser.add_argument('text', type=str, help='Текст заметки.')
    add_parser.set_defaults(func=add_note)

    list_parser = subparsers.add_parser('list', help='Вывести список всех заметок.')
    list_parser.set_defaults(func=list_notes)

    search_parser = subparsers.add_parser('search', help='Ищет заметки по ключевому слову.')
    search_parser.add_argument('keyword', type=str, help='Ключевое слово для поиска.')
    search_parser.set_defaults(func=search_notes)

    delete_parser = subparsers.add_parser('delete', help='Удаляет заметку по её индексу.')
    delete_parser.add_argument('index', type=int, help='Индекс заметки для удаления.')
    delete_parser.set_defaults(func=delete_note)

    args = parser.parse_args()
    if hasattr(args, 'func'):
        args.func(args.index if args.command == 'delete' else None)

if __name__ == '__main__':
    main()