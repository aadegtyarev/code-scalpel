from __future__ import annotations

import argparse
from pathlib import Path

from notes_storage import NoteStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notes-cli")
    parser.add_argument(
        "--storage",
        default="notes.json",
        help="Path to JSON storage file",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add a note")
    add_parser.add_argument("text")

    subparsers.add_parser("list", help="List notes")

    search_parser = subparsers.add_parser("search", help="Search notes")
    search_parser.add_argument("query")

    delete_parser = subparsers.add_parser("delete", help="Delete a note")
    delete_parser.add_argument("id", type=int)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = NoteStore(Path(args.storage))

    if args.command == "add":
        note = store.add(args.text)
        print(f"{note.id}: {note.text}")
        return 0

    if args.command == "list":
        for note in store.list():
            print(f"{note.id}: {note.text}")
        return 0

    if args.command == "search":
        for note in store.search(args.query):
            print(f"{note.id}: {note.text}")
        return 0

    if args.command == "delete":
        deleted = store.delete(args.id)
        print("deleted" if deleted else "not found")
        return 0 if deleted else 1

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
