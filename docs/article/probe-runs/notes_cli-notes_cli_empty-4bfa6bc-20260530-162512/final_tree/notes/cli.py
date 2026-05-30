import argparse
import json
import os

def add(text, notes_file='notes.json'):
    if not os.path.exists(notes_file):
        with open(notes_file, 'w') as f:
            json.dump({}, f)
    with open(notes_file, 'r') as f:
        notes = json.load(f)
    note_id = len(notes) + 1
    while str(note_id) in notes:
        note_id += 1
    notes[str(note_id)] = text
    with open(notes_file, 'w') as f:
        json.dump(notes, f, indent=4)
    print(f"Заметка {note_id} добавлена")

def list_notes(notes_file='notes.json'):
    if not os.path.exists(notes_file):
        with open(notes_file, 'w') as f:
            json.dump({}, f)
    with open(notes_file, 'r') as f:
        notes = json.load(f)
    if not notes:
        print("Нет заметок")
    else:
        for note_id, text in notes.items():
            print(f"{note_id}: {text}")

def search(query, notes_file='notes.json'):
    with open(notes_file, 'r') as f:
        notes = json.load(f)
    results = [f"{note_id}: {text}" for note_id, text in notes.items() if query.lower() in text.lower()]
    if not results:
        print("Ничего не найдено")
    else:
        for result in results:
            print(result)

def delete(note_id, notes_file='notes.json'):
    with open(notes_file, 'r') as f:
        notes = json.load(f)
    if str(note_id) in notes:
        del notes[str(note_id)]
        with open(notes_file, 'w') as f:
            json.dump(notes, f, indent=4)
        print(f"Заметка {note_id} удалена")
    else:
        print("Заметка не найдена")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CLI для заметок")
    subparsers = parser.add_subparsers(dest='command')

    add_parser = subparsers.add_parser('add', help='Добавить новую заметку')
    add_parser.add_argument('text', type=str, help='Текст заметки')
    add_parser.set_defaults(func=add)

    list_parser = subparsers.add_parser('list', help='Вывести список всех заметок')
    list_parser.set_defaults(func=list_notes)

    search_parser = subparsers.add_parser('search', help='Искать заметки по ключевым словам')
    search_parser.add_argument('query', type=str, help='Ключевые слова для поиска')
    search_parser.set_defaults(func=search)

    delete_parser = subparsers.add_parser('delete', help='Удалить заметку по её идентификатору')
    delete_parser.add_argument('note_id', type=int, help='Идентификатор заметки')
    delete_parser.set_defaults(func=delete)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
    else:
        args.func(args)