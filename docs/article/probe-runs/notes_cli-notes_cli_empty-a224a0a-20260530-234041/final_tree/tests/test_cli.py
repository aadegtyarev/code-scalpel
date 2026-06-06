from notes_cli.cli import main


def test_add_list_search_and_delete(tmp_path, capsys):
    storage = tmp_path / "notes.json"

    exit_code = main(["--storage", str(storage), "add", "Shopping", "Buy milk"])
    assert exit_code == 0
    added = capsys.readouterr().out.strip()
    assert "Shopping" in added

    exit_code = main(["--storage", str(storage), "list"])
    assert exit_code == 0
    listed = capsys.readouterr().out.strip()
    assert "Shopping" in listed
    assert "Buy milk" in listed

    exit_code = main(["--storage", str(storage), "search", "milk"])
    assert exit_code == 0
    searched = capsys.readouterr().out.strip()
    assert "Shopping" in searched

    note_id = added.split(":", 1)[0]
    exit_code = main(["--storage", str(storage), "delete", note_id])
    assert exit_code == 0
    assert capsys.readouterr().out == ""

    exit_code = main(["--storage", str(storage), "delete", "missing"])
    assert exit_code == 1
    missing = capsys.readouterr().out.strip()
    assert "not found" in missing
