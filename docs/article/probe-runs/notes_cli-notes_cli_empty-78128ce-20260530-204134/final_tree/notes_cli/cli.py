from __future__ import annotations

import argparse
from pathlib import Path
import sys

from .storage import NotesStore

DEFAULT_STORAGE = Path.home() / ".notes-cli.json"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notes-cli")
    parser.add_argument(
        "--storage",
        default=str(DEFAULT_STORAGE),
        help="Path to the JSON storage file",
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


def format_note(note) -> str:
    return f"{note.id}: {note.text} ({note.created_at})"


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = NotesStore(args.storage)

    if args.command == "add":
        note = store.add(args.text)
        print(format_note(note))
        return 0

    if args.command == "list":
        for note in store.list():
            print(format_note(note))
        return 0

    if args.command == "search":
        for note in store.search(args.query):
            print(format_note(note))
        return 0

    if args.command == "delete":
        if store.delete(args.id):
            return 0
        print(f"note {args.id} not found", file=sys.stderr)
        return 1

    return 1
