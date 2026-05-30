import sys
from src.storage import Storage

def main():
    storage = Storage()
    if len(sys.argv) < 2:
        print("Usage: python notes.py [add|list|search|delete] <args>")
        return

    command = sys.argv[1]
    if command == 'add':
        if len(sys.argv) < 3:
            print("Usage: python notes.py add \"Текст заметки\"")
            return
        storage.add_note(' '.join(sys.argv[2:]))
        print("Заметка добавлена")
    elif command == 'list':
        notes = storage.list_notes()
        for i, note in enumerate(notes):
            print(f"{i}: {note}")
    elif command == 'search':
        if len(sys.argv) < 3:
            print("Usage: python notes.py search \"ключевое слово\"")
            return
        keyword = sys.argv[2]
        notes = storage.search_notes(keyword)
        for i, note in enumerate(notes):
            print(f"{i}: {note}")
    elif command == 'delete':
        if len(sys.argv) < 3:
            print("Usage: python notes.py delete <индекс>")
            return
        try:
            index = int(sys.argv[2])
            storage.delete_note(index)
            print(f"Заметка {index} удалена")
        except ValueError:
            print("Индекс должен быть числом")
    else:
        print("Неизвестная команда")

if __name__ == "__main__":
    main()