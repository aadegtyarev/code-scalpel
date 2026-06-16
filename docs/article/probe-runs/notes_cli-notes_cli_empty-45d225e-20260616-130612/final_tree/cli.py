"""CLI-интерфейс для заметок."""

import argparse
import sys

from notes_storage import add_note, delete_note, list_notes, search_notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="notes", description="Управление заметками")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    add_parser = sub.add_parser("add", help="Добавить заметку")
    add_parser.add_argument("--title", required=True, help="Заголовок")
    add_parser.add_argument("--content", required=True, help="Содержимое")

    # list
    sub.add_parser("list", help="Показать все заметки")

    # search
    search_parser = sub.add_parser("search", help="Найти заметки")
    search_parser.add_argument("--query", required=True, help="Поисковый запрос")

    # delete
    delete_parser = sub.add_parser("delete", help="Удалить заметку")
    delete_parser.add_argument("--id", type=int, required=True, help="ID заметки")

    args = parser.parse_args(argv)

    if args.command == "add":
        note_id = add_note(args.title, args.content)
        print(f"Added note {note_id}")
        return 0

    if args.command == "list":
        notes = list_notes()
        if not notes:
            print("No notes found.")
            return 0
        for n in notes:
            print(f"{n['id']}. {n['title']}")
        return 0

    if args.command == "search":
        results = search_notes(args.query)
        if not results:
            print("No matches.")
            return 0
        for n in results:
            print(f"{n['id']}. {n['title']}")
        return 0

    if args.command == "delete":
        ok = delete_note(args.id)
        if ok:
            print(f"Deleted note {args.id}")
            return 0
        else:
            print(f"Note {args.id} not found.")
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
