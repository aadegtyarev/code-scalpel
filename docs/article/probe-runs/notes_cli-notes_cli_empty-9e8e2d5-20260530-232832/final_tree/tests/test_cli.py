from notes_cli.cli import main


def test_add_list_search_delete(tmp_path, capsys):
    storage = tmp_path / "notes.json"

    assert main(["--storage", str(storage), "add", "Milk", "Buy milk"]) == 0
    add_output = capsys.readouterr().out.strip()
    note_id = add_output.split(" | ", 1)[0]
    assert note_id

    assert main(["--storage", str(storage), "list"]) == 0
    list_output = capsys.readouterr().out.strip().splitlines()
    assert len(list_output) == 1
    assert "Milk" in list_output[0]

    assert main(["--storage", str(storage), "search", "milk"]) == 0
    search_output = capsys.readouterr().out.strip().splitlines()
    assert len(search_output) == 1
    assert "Buy milk" in search_output[0]

    assert main(["--storage", str(storage), "delete", note_id]) == 0
    delete_output = capsys.readouterr().out.strip()
    assert note_id in delete_output


def test_delete_missing_note_exits_nonzero(tmp_path, capsys):
    storage = tmp_path / "notes.json"

    exit_code = main(["--storage", str(storage), "delete", "missing"])
    assert exit_code == 2
    assert "note not found" in capsys.readouterr().err
