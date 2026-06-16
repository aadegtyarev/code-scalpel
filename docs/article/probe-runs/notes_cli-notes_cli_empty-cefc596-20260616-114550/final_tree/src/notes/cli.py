from __future__ import annotations

import argparse
import sys

from notes.storage import Note, NotesStorage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notes")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Создать заметку")
    p_add.add_argument("--title", required=True)
    p_add.add_argument("--body", required=True)

    sub.add_parser("list", help="Показать все заметки")

    p_search = sub.add_parser("search", help="Найти заметки")
    p_search.add_argument("query")

    p_delete = sub.add_parser("delete", help="Удалить заметку")
    p_delete.add_argument("id", type=int)

    return parser


def main(argv: list[str] | None = None, storage_path: str = "notes.json") -> int:
    """Точка входа. Возвращает код выхода (0 — успех, 1 — ошибка)."""
    parser = build_parser()
    args = parser.parse_args(argv)

    store = NotesStorage(storage_path)

    match args.command:
        case "add":
            note = store.add(Note(title=args.title, body=args.body))
            print(note.id)
            return 0

        case "list":
            notes = store.get_all()
            if not notes:
                return 0
            for n in notes:
                print(f"{n.id}. {n.title}")
                print(f"   {n.body}")
            return 0

        case "search":
            results = store.search(args.query)
            for n in results:
                print(f"{n.id}. {n.title}")
                print(f"   {n.body}")
            return 0

        case "delete":
            try:
                store.delete(args.id)
                print(f"Заметка {args.id} удалена")
            except KeyError:
                print(f"Заметка с id {args.id} не найдена", file=sys.stderr)
                return 1
            return 0

        case _:
            parser.print_help()
            return 1


if __name__ == "__main__":
    sys.exit(main())
