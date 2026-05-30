import sys
from notes import add, list_notes, search, delete

def main():
    if len(sys.argv) < 2:
        print("Использование: python notes_cli.py [команда] [аргументы]")
        return

    command = sys.argv[1]
    args = sys.argv[2:]

    if command == 'add':
        if len(args) < 1:
            print("Использование: python notes_cli.py add [текст заметки]")
        else:
            add(' '.join(args))
            print("Заметка добавлена")
    elif command == 'list':
        notes = list_notes()
        for i, note in enumerate(notes):
            print(f"{i}: {note}")
    elif command == 'search':
        if len(args) < 1:
            print("Использование: python notes_cli.py search [ключевое слово]")
        else:
            results = search(' '.join(args))
            for i, note in enumerate(results):
                print(f"{i}: {note}")
    elif command == 'delete':
        if len(args) < 1:
            print("Использование: python notes_cli.py delete [индекс заметки]")
        else:
            try:
                index = int(args[0])
                delete(index)
                print(f"Заметка с индексом {index} удалена")
            except ValueError:
                print("Индекс должен быть числом")
    else:
        print(f"Неизвестная команда: {command}")

if __name__ == "__main__":
    main()