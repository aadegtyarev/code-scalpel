import pytest
from notes_cli.cli import main

def test_help(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(['--help'])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert 'Usage: notes-cli [OPTIONS] COMMAND [ARGS]...' in captured.out