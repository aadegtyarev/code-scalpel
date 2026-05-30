import argparse
import json
import os

def add(text):
    if not os.path.exists('storage.json'):
        with open('storage.json', 'w') as f:
            json.dump([], f)
    with open('storage.json', 'r+') as f:
        notes = json.load(f)
        if text not in notes:
            notes.append(text)
            f.seek(0)
            json.dump(notes, f)


def list_notes():
    if not os.path.exists('storage.json') or os.stat('storage.json').st_size == 0:
        print("Нет заметок")
        return
    with open('storage.json', 'r') as f:
        notes = json.load(f)
        for i, note in enumerate(notes):
            print(f"{i + 1}. {note}")

def search(query):
    if not os.path.exists('storage.json') or os.stat('storage.json').st_size == 0:
        print("Нет заметок")
        return
    with open('storage.json', 'r') as f:
        notes = json.load(f)
        results = [note for note in notes if query.lower() in note.lower()]
        if not results:
            print("Заметки не найдены")
        else:
            for i, result in enumerate(results):
                print(f"{i + 1}. {result}")

def delete(index):
    if not os.path.exists('storage.json') or os.stat('storage.json').st_size == 0:
        print("Нет заметок")
        return
    with open('storage.json', 'r+') as f:
        notes = json.load(f)
        if index < 1 or index > len(notes):
            print("Неверный индекс")
        else:
            del notes[index - 1]
            f.seek(0)
            json.dump(notes, f)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Notes CLI")
    subparsers = parser.add_subparsers(dest='command')

    add_parser = subparsers.add_parser('add', help='Добавить новую заметку')
    add_parser.add_argument('text', type=str, help='Текст заметки')
    add_parser.set_defaults(func=add)

    list_parser = subparsers.add_parser('list', help='Вывести список всех заметок')
    list_parser.set_defaults(func=list_notes)

    search_parser = subparsers.add_parser('search', help='Искать заметки по ключевым словам')
    search_parser.add_argument('query', type=str, help='Ключевые слова для поиска')
    search_parser.set_defaults(func=search)

    delete_parser = subparsers.add_parser('delete', help='Удалить заметку по её индексу')
    delete_parser.add_argument('index', type=int, help='Индекс заметки')
    delete_parser.set_defaults(func=delete)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
    else:
        args.func(args)