import argparse
import json
import os

def add(text):
    notes = load_notes()
    note_id = len(notes) + 1
    notes[str(note_id)] = text
    save_notes(notes)
    print(f"Заметка {note_id} добавлена")

def list_notes():
    notes = load_notes()
    if not notes:
        print("Нет заметок")
    else:
        for note_id, text in notes.items():
            print(f"{note_id}: {text}")

def search(query):
    notes = load_notes()
    found = False
    for note_id, text in notes.items():
        if query.lower() in text.lower():
            print(f"{note_id}: {text}")
            found = True
    if not found:
        print("Ничего не найдено")

def delete(note_id):
    notes = load_notes()
    note_id_str = str(note_id)
    if note_id_str in notes:
        del notes[note_id_str]
        save_notes(notes)
        print(f"Заметка {note_id} удалена")
    else:
        print("Заметка не найдена")

def load_notes():
    if not os.path.exists('notes.json'):
        return {}
    with open('notes.json', 'r') as f:
        return json.load(f)

def save_notes(notes):
    with open('notes.json', 'w') as f:
        json.dump(notes, f, indent=4)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CLI для заметок")
    subparsers = parser.add_subparsers(dest='command')

    add_parser = subparsers.add_parser('add', help='Добавить новую заметку')
    add_parser.add_argument('text', type=str, help='Текст заметки')

    list_parser = subparsers.add_parser('list', help='Вывести список всех заметок')

    search_parser = subparsers.add_parser('search', help='Ищет заметки по ключевому слову')
    search_parser.add_argument('query', type=str, help='Ключевое слово для поиска')

    delete_parser = subparsers.add_parser('delete', help='Удаляет заметку по идентификатору')
    delete_parser.add_argument('note_id', type=int, help='Идентификатор заметки')

    args = parser.parse_args()

    if args.command == 'add':
        add(args.text)
    elif args.command == 'list':
        list_notes()
    elif args.command == 'search':
        search(args.query)
    elif args.command == 'delete':
        delete(args.note_id)