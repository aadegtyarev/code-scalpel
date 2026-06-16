"""CLI для управления заметками."""

import argparse
import sys

import notes_manager


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Разобрать аргументы командной строки."""
    parser = argparse.ArgumentParser(description="Управление заметками")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Добавить заметку")
    add_parser.add_argument("text", type=str, help="Текст заметки")

    subparsers.add_parser("list", help="Показать все заметки")

    search_parser = subparsers.add_parser("search", help="Найти заметки")
    search_parser.add_argument("text", type=str, help="Текст для поиска")

    delete_parser = subparsers.add_parser("delete", help="Удалить заметку")
    delete_parser.add_argument("id", type=int, help="ID заметки")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Точка входа. Возвращает код возврата (0 — успех, 1 — ошибка)."""
    args = parse_args(argv)
    path = "notes.json"

    if args.command == "add":
        note = notes_manager.add_note(args.text, path)
        print(f"Note added with id {note['id']}")
        return 0

    elif args.command == "list":
        notes = notes_manager.list_notes(path)
        for n in notes:
            print(f"{n['id']}: {n['text']} ({n['timestamp']})")
        return 0

    elif args.command == "search":
        notes = notes_manager.search_notes(args.text, path)
        if not notes:
            print("No notes found")
        else:
            for n in notes:
                print(f"{n['id']}: {n['text']} ({n['timestamp']})")
        return 0

    elif args.command == "delete":
        if notes_manager.delete_note(args.id, path):
            print("Note deleted")
            return 0
        else:
            print("Note not found")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
