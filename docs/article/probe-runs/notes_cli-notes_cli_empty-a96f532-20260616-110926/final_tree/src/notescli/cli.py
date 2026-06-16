"""CLI entry point for notescli."""

import argparse
import sys
from typing import Any

from notescli.storage import add_note, delete_note, list_notes, search_notes


def _print_note(note: dict[str, Any]) -> None:
    print(f"  id: {note['id']}")
    print(f"  title: {note['title']}")
    print(f"  created: {note['created_at']}")
    print(f"  content: {note['content']}")
    print()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notescli", description="Заметки в терминале")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    p_add = sub.add_parser("add", help="Добавить заметку")
    p_add.add_argument("--title", required=True, help="Заголовок заметки")
    p_add.add_argument("--content", required=True, help="Текст заметки")

    # list
    sub.add_parser("list", help="Показать все заметки")

    # search
    p_search = sub.add_parser("search", help="Поиск заметок")
    p_search.add_argument("--query", required=True, help="Строка поиска")

    # delete
    p_delete = sub.add_parser("delete", help="Удалить заметку")
    p_delete.add_argument("--id", required=True, help="ID заметки")

    return parser


def main(argv: list[str] | None = None) -> None:
    """Точка входа. Принимает argv для тестирования."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    try:
        if args.command == "add":
            note_id = add_note(args.title, args.content)
            print(note_id)

        elif args.command == "list":
            notes = list_notes()
            if not notes:
                print("No notes")
            else:
                for n in notes:
                    _print_note(n)

        elif args.command == "search":
            results = search_notes(args.query)
            if not results:
                print("No matches")
            else:
                for n in results:
                    _print_note(n)

        elif args.command == "delete":
            ok = delete_note(args.id)
            if ok:
                print("Deleted")
            else:
                print("Note not found")

    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
