import argparse
import json
import os

def load_notes():
    if not os.path.exists('notes.json'):
        return []
    with open('notes.json', 'r') as f:
        return json.load(f)

def save_notes(notes):
    with open('notes.json', 'w') as f:
        json.dump(notes, f, indent=4)

def add_note(text):
    notes = load_notes()
    note = {
        'text': text,
        'label': len(notes) + 1
    }
    notes.append(note)
    save_notes(notes)
    print(f'Заметка добавлена: {note}')

def list_notes():
    notes = load_notes()
    if not notes:
        print('Нет заметок.')
        return
    for note in notes:
        print(f'{note['text']} (метка: {note['label']})')

def search_notes(keyword):
    notes = load_notes()
    found_notes = [note for note in notes if keyword.lower() in note['text'].lower()]
    if not found_notes:
        print('Нет заметок, содержащих ключевое слово.')
        return
    for note in found_notes:
        print(f'{note['text']} (метка: {note['label']})')

def delete_note(label):
    notes = load_notes()
    notes = [note for note in notes if note['label'] != int(label)]
    save_notes(notes)
    print(f'Заметка с меткой {label} удалена.')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='CLI для заметок')
    subparsers = parser.add_subparsers(dest='command')

    add_parser = subparsers.add_parser('add', help='Добавить новую заметку')
    add_parser.add_argument('text', type=str, help='Текст заметки')

    list_parser = subparsers.add_parser('list', help='Вывести все заметки')

    search_parser = subparsers.add_parser('search', help='Найти заметки по ключевому слову')
    search_parser.add_argument('keyword', type=str, help='Ключевое слово для поиска')

    delete_parser = subparsers.add_parser('delete', help='Удалить заметку по метке')
    delete_parser.add_argument('label', type=int, help='Метка заметки для удаления')

    args = parser.parse_args()

    if args.command == 'add':
        add_note(args.text)
    elif args.command == 'list':
        list_notes()
    elif args.command == 'search':
        search_notes(args.keyword)
    elif args.command == 'delete':
        delete_note(args.label)
