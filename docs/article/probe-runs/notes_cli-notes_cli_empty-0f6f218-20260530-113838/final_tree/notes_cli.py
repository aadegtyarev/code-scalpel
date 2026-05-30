import sys
from storage import NoteStorage

def main():
    storage = NoteStorage()
    if len(sys.argv) < 2:
        print("Необходимо указать команду: add, list, search или delete.")
        return

    command = sys.argv[1]
    if command == 'add':
        if len(sys.argv) < 3:
            print('Использование: python notes_cli.py add "заметка"')
            return
        note = ' '.join(sys.argv[2:])
        storage.add(note)
        print(f'Заметка добавлена: {note}')
    elif command == 'list':
        notes = storage.list()
        if not notes:
            print('Нет заметок.')
        else:
            for i, note in enumerate(notes):
                print(f'{i}: {note}')
    elif command == 'search':
        if len(sys.argv) < 3:
            print('Использование: python notes_cli.py search "ключевое слово"')
            return
        keyword = sys.argv[2]
        results = storage.search(keyword)
        if not results:
            print(f'Нет заметок, содержащих "{keyword}".')
        else:
            for i, note in enumerate(results):
                print(f'{i}: {note}')
    elif command == 'delete':
        if len(sys.argv) < 3:
            print('Использование: python notes_cli.py delete <номер заметки>')
            return
        try:
            index = int(sys.argv[2])
            storage.delete(index)
            print(f'Заметка {index} удалена.')
        except ValueError:
            print('Неверный номер заметки.')
    else:
        print('Неизвестная команда. Используйте: add, list, search или delete.')

if __name__ == '__main__':
    main()