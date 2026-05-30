import pytest
from notes.cli import main
def test_add(monkeypatch, capsys):
    monkeypatch.setattr('sys.argv', ['notes/cli.py', 'add', 'Тестовая заметка'])
    main()
    captured = capsys.readouterr()
    assert captured.out == ''


def test_list(monkeypatch, capsys):
    storage = Storage()
    storage.notes = []  # Clear existing notes before running the test
    storage.add('Тестовая заметка')
    monkeypatch.setattr('sys.argv', ['notes/cli.py', 'list'])
    main()
    captured = capsys.readouterr()
    assert captured.out == '0: Тестовая заметка\n'


def test_search(monkeypatch, capsys):
    storage = Storage()
    storage.add('Тестовая заметка')
    monkeypatch.setattr('sys.argv', ['notes/cli.py', 'search', 'заметка'])
    main()
    captured = capsys.readouterr()
    assert captured.out == '0: Тестовая заметка\n'


def test_delete(monkeypatch, capsys):
    storage = Storage()
    storage.add('Тестовая заметка')
    monkeypatch.setattr('sys.argv', ['notes/cli.py', 'delete', '0'])
    main()
    captured = capsys.readouterr()
    assert captured.out == ''