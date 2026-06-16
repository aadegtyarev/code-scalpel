"""Тесты CLI для заметок."""

from unittest.mock import patch

from cli import main


def test_add(capsys):
    with patch("notes_manager.add_note") as mock_add:
        mock_add.return_value = {
            "id": 1,
            "text": "test note",
            "timestamp": "2026-01-01T00:00:00",
        }
        ret = main(["add", "test note"])
        out, _ = capsys.readouterr()

    assert ret == 0
    assert out.strip() == "Note added with id 1"
    mock_add.assert_called_once_with("test note", "notes.json")


def test_list_empty(capsys):
    with patch("notes_manager.list_notes") as mock_list:
        mock_list.return_value = []
        ret = main(["list"])
        out, _ = capsys.readouterr()

    assert ret == 0
    assert out.strip() == ""


def test_list_with_notes(capsys):
    with patch("notes_manager.list_notes") as mock_list:
        mock_list.return_value = [
            {"id": 1, "text": "first", "timestamp": "2026-01-01T00:00:00"},
            {"id": 2, "text": "second", "timestamp": "2026-01-02T00:00:00"},
        ]
        ret = main(["list"])
        out, _ = capsys.readouterr()

    assert ret == 0
    lines = out.strip().splitlines()
    assert lines == [
        "1: first (2026-01-01T00:00:00)",
        "2: second (2026-01-02T00:00:00)",
    ]


def test_search_found(capsys):
    with patch("notes_manager.search_notes") as mock_search:
        mock_search.return_value = [
            {"id": 1, "text": "buy milk", "timestamp": "2026-01-01T00:00:00"},
        ]
        ret = main(["search", "milk"])
        out, _ = capsys.readouterr()

    assert ret == 0
    assert out.strip() == "1: buy milk (2026-01-01T00:00:00)"
    mock_search.assert_called_once_with("milk", "notes.json")


def test_search_not_found(capsys):
    with patch("notes_manager.search_notes") as mock_search:
        mock_search.return_value = []
        ret = main(["search", "nonexistent"])
        out, _ = capsys.readouterr()

    assert ret == 0
    assert out.strip() == "No notes found"


def test_delete_found(capsys):
    with patch("notes_manager.delete_note") as mock_delete:
        mock_delete.return_value = True
        ret = main(["delete", "1"])
        out, _ = capsys.readouterr()

    assert ret == 0
    assert out.strip() == "Note deleted"
    mock_delete.assert_called_once_with(1, "notes.json")


def test_delete_not_found(capsys):
    with patch("notes_manager.delete_note") as mock_delete:
        mock_delete.return_value = False
        ret = main(["delete", "999"])
        out, _ = capsys.readouterr()

    assert ret == 1
    assert out.strip() == "Note not found"
    mock_delete.assert_called_once_with(999, "notes.json")
