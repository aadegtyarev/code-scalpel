import pytest
from main import main
from notes import add

def test_add(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(['main.py', 'add', 'Test note'])
    captured = capsys.readouterr()
    assert 'Note added with ID' in captured.out
    assert excinfo.value.code == 0

def test_list(capsys):
    add('First note')
    add('Second note')
    with pytest.raises(SystemExit) as excinfo:
        main(['main.py', 'list'])
    captured = capsys.readouterr()
    assert '1: First note' in captured.out
    assert '2: Second note' in captured.out
    assert excinfo.value.code == 0

def test_search(capsys):
    add('Test search')
    with pytest.raises(SystemExit) as excinfo:
        main(['main.py', 'search', 'search'])
    captured = capsys.readouterr()
    assert '1: Test search' in captured.out
    assert excinfo.value.code == 0

def test_delete(capsys):
    note_id = add('Note to delete')
    with pytest.raises(SystemExit) as excinfo:
        main(['main.py', 'delete', str(note_id)])
    captured = capsys.readouterr()
    assert f'Note with ID {note_id} deleted' in captured.out
    assert excinfo.value.code == 0