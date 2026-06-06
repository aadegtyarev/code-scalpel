from __future__ import annotations

import json

from notes_cli import main
from notes_storage import NoteStore


def test_add_and_list_notes(tmp_path, capsys):
    storage = tmp_path / "notes.json"

    exit_code = main(["--storage", str(storage), "add", "Купить молоко"])
    assert exit_code == 0

    out = capsys.readouterr().out.strip()
    assert out == "1: Купить молоко"

    exit_code = main(["--storage", str(storage), "list"])
    assert exit_code == 0

    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["1: Купить молоко"]

    data = json.loads(storage.read_text(encoding="utf-8"))
    assert data == [
        {
            "id": 1,
            "text": "Купить молоко",
            "created_at": data[0]["created_at"],
        }
    ]


def test_search_notes_by_substring(tmp_path, capsys):
    storage = tmp_path / "notes.json"
    store = NoteStore(storage)
    store.add("Купить молоко")
    store.add("Позвонить врачу")
    store.add("Молоко и хлеб")

    exit_code = main(["--storage", str(storage), "search", "молоко"])
    assert exit_code == 0

    out = capsys.readouterr().out.strip().splitlines()
    assert out == ["1: Купить молоко", "3: Молоко и хлеб"]


def test_delete_existing_and_missing_note(tmp_path, capsys):
    storage = tmp_path / "notes.json"
    store = NoteStore(storage)
    store.add("Купить молоко")
    store.add("Позвонить врачу")

    exit_code = main(["--storage", str(storage), "delete", "1"])
    assert exit_code == 0
    assert capsys.readouterr().out.strip() == "deleted"

    exit_code = main(["--storage", str(storage), "delete", "99"])
    assert exit_code == 1
    assert capsys.readouterr().out.strip() == "not found"

    out = main(["--storage", str(storage), "list"])
    assert out == 0
    assert capsys.readouterr().out.strip().splitlines() == ["2: Позвонить врачу"]
