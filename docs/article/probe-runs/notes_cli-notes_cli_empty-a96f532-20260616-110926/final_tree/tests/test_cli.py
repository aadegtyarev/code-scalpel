"""Tests for notescli.cli — uses monkeypatch.chdir for isolation."""

from pathlib import Path

import pytest

from notescli.cli import main


def test_add_prints_id(capsys, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    main(["add", "--title", "Hello", "--content", "World"])
    out, _ = capsys.readouterr()
    nid = out.strip()
    assert len(nid) > 0
    assert nid.isascii()


def test_list_empty(capsys, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    main(["list"])
    out, _ = capsys.readouterr()
    assert "No notes" in out


def test_list_with_notes(capsys, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    main(["add", "--title", "T1", "--content", "C1"])
    main(["add", "--title", "T2", "--content", "C2"])
    out, _ = capsys.readouterr()  # flush from add
    main(["list"])
    out, _ = capsys.readouterr()
    assert "T1" in out
    assert "T2" in out
    assert "C1" in out
    assert "C2" in out


def test_search_matches(capsys, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    main(["add", "--title", "Python", "--content", "learning"])
    capsys.readouterr()  # flush
    main(["search", "--query", "Python"])
    out, _ = capsys.readouterr()
    assert "Python" in out
    assert "learning" in out


def test_search_no_match(capsys, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    main(["add", "--title", "Python", "--content", "learning"])
    capsys.readouterr()  # flush
    main(["search", "--query", "Java"])
    out, _ = capsys.readouterr()
    assert "No matches" in out


def test_delete_existing(capsys, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    main(["add", "--title", "Del", "--content", "me"])
    out, _ = capsys.readouterr()
    nid = out.strip()
    main(["delete", "--id", nid])
    out, _ = capsys.readouterr()
    assert "Deleted" in out


def test_delete_non_existent(capsys, monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)
    main(["delete", "--id", "00000000-0000-0000-0000-000000000000"])
    out, _ = capsys.readouterr()
    assert "Note not found" in out


def test_runtime_error_exits(monkeypatch, tmp_path: Path) -> None:
    """Malformed JSON -> RuntimeError -> sys.exit(1)."""
    monkeypatch.chdir(tmp_path)
    p = tmp_path / "notes.json"
    p.write_text("{{{broken", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["list"])
    assert exc.value.code == 1


def test_argument_error_exits() -> None:
    """Missing required args -> SystemExit(2)."""
    with pytest.raises(SystemExit) as exc:
        main(["add"])
    assert exc.value.code == 2


def test_unknown_command_exits() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["unknown"])
    assert exc.value.code == 2
