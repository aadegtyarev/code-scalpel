import json
import sys
from storage import load_notes, save_notes

def add(note):
    notes = load_notes()
    notes.append(note)
    save_notes(notes)
    print(f"Заметка добавлена: {note}")

def list_notes():
    return load_notes()

def search(query):
    notes = load_notes()
    found_notes = [note for note in notes if query.lower() in note.lower()]
    if not found_notes:
        print("Нет совпадений.")
    else:
        for i, note in enumerate(found_notes, start=1):
            print(f"{i}. {note}")

def delete(index):
    notes = load_notes()
    if 0 < index <= len(notes):
        deleted_note = notes.pop(index - 1)
        save_notes(notes)
        print(f"Заметка удалена: {deleted_note}")
    else:
        print("Неверный индекс.")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Использование: python notes.py [команда] [аргументы]")
    else:
        command = sys.argv[1]
        args = sys.argv[2:] if len(sys.argv) > 2 else []

        if command == "add":
            add(args[0])
        elif command == "list":
            notes = list_notes()
            for i, note in enumerate(notes, start=1):
                print(f"{i}. {note}")
        elif command == "search":
            search(args[0])
        elif command == "delete":
            delete(int(args[0]))
        else:
            print(f"Неизвестная команда: {command}")