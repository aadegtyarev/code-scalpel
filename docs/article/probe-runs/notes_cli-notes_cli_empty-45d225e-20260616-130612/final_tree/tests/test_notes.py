"""Тесты для модуля хранения и CLI заметок."""

import pytest

import notes_storage
from cli import main
from notes_storage import add_note, delete_note, list_notes, search_notes


# ── helpers ──────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _temp_storage(monkeypatch, tmp_path):
    """Перенаправить storage-файл каждой заметки во временную папку."""
    monkeypatch.setattr(notes_storage, "_STORAGE_FILE", str(tmp_path / "notes.json"))
    yield


# ── storage unit tests ───────────────────────────────────────────────

class TestStorage:
    def test_add_and_list(self):
        nid = add_note("Заголовок", "Текст")
        assert isinstance(nid, int)
        assert nid == 1

        notes = list_notes()
        assert len(notes) == 1
        assert notes[0] == {"id": 1, "title": "Заголовок", "content": "Текст"}

    def test_add_increments_id(self):
        id1 = add_note("A", "a")
        id2 = add_note("B", "b")
        id3 = add_note("C", "c")
        assert (id1, id2, id3) == (1, 2, 3)
        assert len(list_notes()) == 3

    def test_list_empty_when_no_file(self):
        assert list_notes() == []

    def test_search_found(self):
        add_note("Купить молоко", "Заехать в магазин")
        add_note("Идея", "Купить хлеб")
        add_note("Другое", "Просто заметка")

        result = search_notes("молоко")
        assert len(result) == 1
        assert result[0]["title"] == "Купить молоко"

        result = search_notes("купить")
        assert len(result) == 2

    def test_search_case_insensitive(self):
        add_note("Python CLI", "Code")
        assert len(search_notes("python")) == 1
        assert len(search_notes("PYTHON")) == 1

    def test_search_not_found(self):
        add_note("Один", "Раз")
        assert search_notes("absent") == []

    def test_delete_existing(self):
        nid = add_note("Удалить", "меня")
        assert delete_note(nid) is True
        assert list_notes() == []

    def test_delete_non_existing(self):
        assert delete_note(999) is False

    def test_delete_only_one(self):
        add_note("A", "a")
        add_note("B", "b")
        add_note("C", "c")
        assert delete_note(2) is True
        notes = list_notes()
        assert [n["id"] for n in notes] == [1, 3]


# ── CLI integration tests ────────────────────────────────────────────

class TestCli:
    def test_cli_add(self, capsys):
        rc = main(["add", "--title", "Заголовок", "--content", "Текст"])
        out, _ = capsys.readouterr()
        assert rc == 0
        assert "Added note 1" in out
        assert len(list_notes()) == 1

    def test_cli_list_empty(self, capsys):
        rc = main(["list"])
        out, _ = capsys.readouterr()
        assert rc == 0
        assert out.strip() == "No notes found."

    def test_cli_list_with_notes(self, capsys):
        add_note("Первая", "раз")
        add_note("Вторая", "два")
        rc = main(["list"])
        out, _ = capsys.readouterr()
        assert rc == 0
        assert "1. Первая" in out
        assert "2. Вторая" in out

    def test_cli_search_match(self, capsys):
        add_note("Кофе", "Купить зёрна")
        rc = main(["search", "--query", "кофе"])
        out, _ = capsys.readouterr()
        assert rc == 0
        assert "1. Кофе" in out

    def test_cli_search_no_match(self, capsys):
        add_note("Чай", "Зелёный")
        rc = main(["search", "--query", "absent"])
        out, _ = capsys.readouterr()
        assert rc == 0
        assert out.strip() == "No matches."

    def test_cli_delete_success(self, capsys):
        nid = add_note("Удаляемая", "bye")
        rc = main(["delete", "--id", str(nid)])
        out, _ = capsys.readouterr()
        assert rc == 0
        assert f"Deleted note {nid}" in out
        assert list_notes() == []

    def test_cli_delete_not_found(self, capsys):
        rc = main(["delete", "--id", "999"])
        out, _ = capsys.readouterr()
        assert rc == 1
        assert "Note 999 not found." in out

    def test_cli_missing_title(self):
        with pytest.raises(SystemExit) as exc:
            main(["add", "--content", "x"])
        assert exc.value.code == 2

    def test_cli_missing_content(self):
        with pytest.raises(SystemExit) as exc:
            main(["add", "--title", "x"])
        assert exc.value.code == 2

    def test_cli_missing_query(self):
        with pytest.raises(SystemExit) as exc:
            main(["search"])
        assert exc.value.code == 2

    def test_cli_missing_id(self):
        with pytest.raises(SystemExit) as exc:
            main(["delete"])
        assert exc.value.code == 2

    def test_cli_no_command(self):
        with pytest.raises(SystemExit) as exc:
            main([])
        assert exc.value.code == 2
