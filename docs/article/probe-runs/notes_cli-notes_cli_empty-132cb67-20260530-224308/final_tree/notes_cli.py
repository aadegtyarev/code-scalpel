from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_STORAGE = Path("notes.json")


@dataclass(slots=True)
class Note:
    id: int
    text: str

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "text": self.text}


def load_notes(storage: Path) -> list[Note]:
    if not storage.exists():
        return []
    data = json.loads(storage.read_text(encoding="utf-8"))
    return [Note(id=int(item["id"]), text=str(item["text"])) for item in data]


def save_notes(storage: Path, notes: list[Note]) -> None:
    storage.write_text(
        json.dumps([note.to_dict() for note in notes], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_note(storage: Path, text: str) -> Note:
    notes = load_notes(storage)
    next_id = max((note.id for note in notes), default=0) + 1
    note = Note(id=next_id, text=text)
    notes.append(note)
    save_notes(storage, notes)
    return note


def list_notes(storage: Path) -> list[Note]:
    return load_notes(storage)


def search_notes(storage: Path, query: str) -> list[Note]:
    query_lower = query.lower()
    return [note for note in load_notes(storage) if query_lower in note.text.lower()]


def delete_note(storage: Path, note_id: int) -> bool:
    notes = load_notes(storage)
    filtered = [note for note in notes if note.id != note_id]
    if len(filtered) == len(notes):
        return False
    save_notes(storage, filtered)
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="notes-cli")
    parser.add_argument("--storage", type=Path, default=DEFAULT_STORAGE)
    subparsers = parser.add_subparsers(dest="command", required=True)

    add_parser = subparsers.add_parser("add")
    add_parser.add_argument("text")

    subparsers.add_parser("list")

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("query")

    delete_parser = subparsers.add_parser("delete")
    delete_parser.add_argument("id", type=int)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "add":
        note = add_note(args.storage, args.text)
        print(f"{note.id}: {note.text}")
        return 0
    if args.command == "list":
        for note in list_notes(args.storage):
            print(f"{note.id}: {note.text}")
        return 0
    if args.command == "search":
        for note in search_notes(args.storage, args.query):
            print(f"{note.id}: {note.text}")
        return 0
    if args.command == "delete":
        if delete_note(args.storage, args.id):
            print(f"Deleted {args.id}")
            return 0
        print(f"Note {args.id} not found")
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
