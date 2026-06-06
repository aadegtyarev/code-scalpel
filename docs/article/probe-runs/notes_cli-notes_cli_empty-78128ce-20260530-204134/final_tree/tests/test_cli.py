from notes_cli.cli import main


def test_add_list_search_delete_flow(tmp_path, capsys):
    storage = tmp_path / "notes.json"

    exit_code = main(["--storage", str(storage), "add", "Buy milk"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "1: Buy milk" in out

    exit_code = main(["--storage", str(storage), "list"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "1: Buy milk" in out

    exit_code = main(["--storage", str(storage), "search", "milk"])
    assert exit_code == 0
    out = capsys.readouterr().out
    assert "1: Buy milk" in out

    exit_code = main(["--storage", str(storage), "delete", "1"])
    assert exit_code == 0
    assert capsys.readouterr().out == ""

    exit_code = main(["--storage", str(storage), "list"])
    assert exit_code == 0
    assert capsys.readouterr().out == ""


def test_delete_missing_note_returns_error(tmp_path, capsys):
    storage = tmp_path / "notes.json"

    exit_code = main(["--storage", str(storage), "delete", "99"])

    assert exit_code == 1
    assert capsys.readouterr().err == "note 99 not found\n"
