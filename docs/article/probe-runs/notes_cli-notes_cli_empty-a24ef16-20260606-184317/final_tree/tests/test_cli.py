import pytest
from notes.cli import main
def test_add(capsys):
    main(['add', 'Test note'])
    captured = capsys.readouterr()
    assert captured.out == ''

def test_list(capsys):
    main(['list'])
    captured = capsys.readouterr()
    assert captured.out == '0: Test note\n'

def test_search(capsys):
    main(['search', 'Test'])
    captured = capsys.readouterr()
    assert captured.out == '0: Test note\n'

def test_delete(capsys):
    main(['delete', '0'])
    main(['list'])
    captured = capsys.readouterr()
    assert captured.out == ''