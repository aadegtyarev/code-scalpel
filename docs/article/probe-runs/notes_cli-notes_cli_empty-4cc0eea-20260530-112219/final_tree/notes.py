import json
import sys

def add_note(title, content):
    try:
        with open('storage.json', 'r') as file:
            notes = json.load(file)
    except FileNotFoundError:
        notes = {}

    if title in notes:
        print(f'Заметка с названием "{title}" уже существует.')
    else:
        notes[title] = content
        with open('storage.json', 'w') as file:
            json.dump(notes, file)
        print(f'Заметка "{title}" добавлена.')

def list_notes():
    try:
        with open('storage.json', 'r') as file:
            notes = json.load(file)
    except FileNotFoundError:
        notes = {}

    if not notes:
        print('Нет заметок.')
    else:
        for title, content in notes.items():
            print(f'Заметка "{title}": {content}')

def search_notes(query):
    try:
        with open('storage.json', 'r') as file:
            notes = json.load(file)
    except FileNotFoundError:
        notes = {}

    found = False
    for title, content in notes.items():
        if query.lower() in title.lower() or query.lower() in content.lower():
            print(f'Заметка "{title}": {content}')
            found = True

    if not found:
        print('Нет заметок, соответствующих запросу.')

def delete_note(title):
    try:
        with open('storage.json', 'r') as file:
            notes = json.load(file)
    except FileNotFoundError:
        notes = {}

    if title in notes:
        del notes[title]
        with open('storage.json', 'w') as file:
            json.dump(notes, file)
        print(f'Заметка "{title}" удалена.')
    else:
        print(f'Заметка с названием "{title}" не существует.')

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print('Необходимо указать команду.')
    else:
        command = sys.argv[1]
        if command == 'add' and len(sys.argv) > 3:
            add_note(sys.argv[2], ' '.join(sys.argv[3:]))
        elif command == 'list':
            list_notes()
        elif command == 'search' and len(sys.argv) > 2:
            search_notes(sys.argv[2])
        elif command == 'delete' and len(sys.argv) > 2:
            delete_note(sys.argv[2])
        else:
            print('Неверная команда или недостаточно аргументов.')