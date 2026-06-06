import sys
from storage import add_note, list_notes, search_notes, delete_note

def main(argv=None):
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print("Используйте команды: add, list, search, delete")
        return 1

    command = argv[0]
    args = argv[1:]

    if command == "add":
        if len(args) < 1:
            print("Укажите текст заметки")
            return 1
        add_note(args[0])
        print(f"Заметка добавлена: {args[0]}")
    elif command == "list":
        notes = list_notes()
        for i, note in enumerate(notes):
            print(f"{i}: {note}")
    elif command == "search":
        if len(args) < 1:
            print("Укажите ключевое слово для поиска")
            return 1
        results = search_notes(args[0])
        for i, note in enumerate(results):
            print(f"{i}: {note}")
    elif command == "delete":
        if len(args) < 1:
            print("Укажите индекс заметки для удаления")
            return 1
        try:
            index = int(args[0])
            delete_note(index)
            print(f"Заметка с индексом {index} удалена")
        except ValueError:
            print("Некорректный индекс")
            return 1
    else:
        print(f"Неизвестная команда: {command}")
        return 1

if __name__ == "__main__":
    sys.exit(main())