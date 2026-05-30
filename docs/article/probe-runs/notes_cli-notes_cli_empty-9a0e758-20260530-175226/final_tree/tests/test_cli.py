import pytest
from src.notes.cli import main
def test_add_note(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(['add', 'Заметка 1'])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert 'Заметка добавлена' in captured.out
def test_list_notes(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(['list'])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert 'Заметка 1' in captured.out
def test_search_notes(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(['search', 'заметка'])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert 'Заметка 1' in captured.out
def test_delete_note(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(['delete', '0'])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert 'Заметка добавлена' not in captured.out