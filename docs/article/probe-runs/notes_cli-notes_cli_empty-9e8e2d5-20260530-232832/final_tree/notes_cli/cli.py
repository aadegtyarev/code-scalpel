from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from notes_cli.storage import NoteNotFoundError, NoteStore

DEFAULT_STORAGE = Path("notes.json")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notes")
    parser.add_argument(
        "--storage",
        type=Path,
        default=DEFAULT_STORAGE,
        help="Path to JSON storage file",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add", help="Add a note")
    add_parser.add_argument("title", help="Note title")
    add_parser.add_argument("body", nargs="?", default="", help="Note body")

    subparsers.add_parser("list", help="List notes")

    search_parser = subparsers.add_parser("search", help="Search notes")
    search_parser.add_argument("query", help="Search text")

    delete_parser = subparsers.add_parser("delete", help="Delete a note")
    delete_parser.add_argument("note_id", help="Note identifier")

    return parser


def format_note(note) -> str:
    return f"{note.id} | {note.title} | {note.body} | {note.created_at}"


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    store = NoteStore(args.storage)

    if args.command == "add":
        note = store.add(args.title, args.body)
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
        try:
            note = store.delete(args.note_id)
        except NoteNotFoundError:
            print(f"note not found: {args.note_id}")
            return 1
        print(format_note(note))
        return 0

    parser.error(f"unknown command: {args.command}")
