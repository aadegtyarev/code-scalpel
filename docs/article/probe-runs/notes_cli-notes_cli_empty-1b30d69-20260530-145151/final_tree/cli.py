import sys
from storage import add_note, get_notes, search_notes, delete_note

def main():
    if len(sys.argv) < 2:
        print("Использование: python cli.py [add|list|search|delete] [аргументы]")
        return

    command = sys.argv[1]

    if command == 'add':
        if len(sys.argv) != 3:
            print("Использование: python cli.py add \"Заметка\"")")
        else:
            add_note(sys.argv[2])
            print(f"Заметка добавлена: {sys.argv[2]}")

    elif command == 'list':
        notes = get_notes()
        for i, note in enumerate(notes):
            print(f"{i}: {note}")

    elif command == 'search':
        if len(sys.argv) != 3:
            print("Использование: python cli.py search \"Ключевое слово\"")")
        else:
            results = search_notes(sys.argv[2])
            for i, note in enumerate(results):
                print(f"{i}: {note}")

    elif command == 'delete':
        if len(sys.argv) != 3:
            print("Использование: python cli.py delete <индекс>")")
        else:
            try:
                index = int(sys.argv[2])
                delete_note(index)
                print(f"Заметка с индексом {index} удалена.")
            except ValueError:
                print("Индекс должен быть числом.")

    else:
        print(f"Неизвестная команда: {command}")

if __name__ == "__main__":
    main()
