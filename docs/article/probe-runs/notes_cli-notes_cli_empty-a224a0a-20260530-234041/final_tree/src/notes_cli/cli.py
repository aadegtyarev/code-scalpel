from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .storage import NoteStorage


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notes-cli")
    parser.add_argument("--storage", default="notes.json")

    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("title")
    add_parser.add_argument("content", nargs="?")

    subparsers.add_parser("list")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")

    delete_parser = subparsers.add_parser("delete")
    delete_parser.add_argument("id")

    return parser


def format_note(note) -> str:
    parts = [f"{note.id}: {note.title}"]
    if note.content:
        parts.append(note.content)
    parts.append(note.created_at)
    return " | ".join(parts)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    storage = NoteStorage(Path(args.storage))

    if args.command == "add":
        content = args.content if args.content is not None else args.title
        title = args.title if args.content is not None else args.title
        note = storage.add(title, content)
        print(format_note(note))
        return 0

    if args.command == "list":
        for note in storage.load():
            print(format_note(note))
        return 0

    if args.command == "search":
        for note in storage.search(args.query):
            print(format_note(note))
        return 0

    if args.command == "delete":
        if storage.delete(args.id):
            return 0
        print(f"Note {args.id} not found")
        return 1

    return 0
