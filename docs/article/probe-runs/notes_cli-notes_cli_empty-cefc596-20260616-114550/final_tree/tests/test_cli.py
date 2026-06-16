from __future__ import annotations

import pytest

from notes.cli import main


class TestCliAdd:
    def test_add_prints_id(self, tmp_path: pytest.TempPathFactory) -> None:
        p = tmp_path / "notes.json"
        rc = main(["add", "--title", "t", "--body", "b"], storage_path=str(p))
        assert rc == 0

    def test_add_stores(self, tmp_path: pytest.TempPathFactory) -> None:
        p = tmp_path / "notes.json"
        main(["add", "--title", "t", "--body", "b"], storage_path=str(p))
        rc = main(["list"], storage_path=str(p))
        assert rc == 0


class TestCliList:
    def test_list_empty_ok(self, tmp_path: pytest.TempPathFactory) -> None:
        p = tmp_path / "notes.json"
        rc = main(["list"], storage_path=str(p))
        assert rc == 0

    def test_list_after_add(self, tmp_path: pytest.TempPathFactory, capsys) -> None:
        p = tmp_path / "notes.json"
        main(["add", "--title", "Título", "--body", "Cuerpo"], storage_path=str(p))
        capsys.readouterr()  # flush add output
        rc = main(["list"], storage_path=str(p))
        out, _ = capsys.readouterr()
        assert rc == 0
        assert "1." in out
        assert "Título" in out
        assert "Cuerpo" in out


class TestCliSearch:
    def test_search_found(self, tmp_path: pytest.TempPathFactory, capsys) -> None:
        p = tmp_path / "notes.json"
        main(["add", "--title", "Hello", "--body", "world"], storage_path=str(p))
        capsys.readouterr()
        rc = main(["search", "hello"], storage_path=str(p))
        out, _ = capsys.readouterr()
        assert rc == 0
        assert "Hello" in out

    def test_search_not_found(self, tmp_path: pytest.TempPathFactory, capsys) -> None:
        p = tmp_path / "notes.json"
        main(["add", "--title", "Hello", "--body", "world"], storage_path=str(p))
        capsys.readouterr()
        rc = main(["search", "zzz"], storage_path=str(p))
        out, _ = capsys.readouterr()
        assert rc == 0
        assert out == ""


class TestCliDelete:
    def test_delete_existing(self, tmp_path: pytest.TempPathFactory, capsys) -> None:
        p = tmp_path / "notes.json"
        main(["add", "--title", "t", "--body", "b"], storage_path=str(p))
        capsys.readouterr()
        rc = main(["delete", "1"], storage_path=str(p))
        out, _ = capsys.readouterr()
        assert rc == 0
        assert "удалена" in out

    def test_delete_nonexistent(self, tmp_path: pytest.TempPathFactory, capsys) -> None:
        p = tmp_path / "notes.json"
        rc = main(["delete", "1"], storage_path=str(p))
        out, err = capsys.readouterr()
        assert rc == 1
        assert "не найдена" in err


class TestCliError:
    def test_unknown_command(self) -> None:
        with pytest.raises(SystemExit) as exc:
            main(["oops"])
        assert exc.value.code == 2  # argparse default for unknown subcommand
