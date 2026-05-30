import pytest
from io import StringIO
import sys
from notes_cli import main

def test_add(monkeypatch):
    monkeypatch.setattr('sys.argv', ['notes_cli.py', 'add', 'Заметка 1'])
    monkeypatch.setattr('sys.stdout', StringIO())
    main()
    assert 'Заметка 1' in sys.stdout.getvalue()

def test_list(monkeypatch):
    monkeypatch.setattr('sys.argv', ['notes_cli.py', 'list'])
    monkeypatch.setattr('sys.stdout', StringIO())
    main()
    assert 'Заметка 1' in sys.stdout.getvalue()
    assert 'Заметка 2' in sys.stdout.getvalue()

def test_search(monkeypatch):
    monkeypatch.setattr('sys.argv', ['notes_cli.py', 'search', 'Заметка'])
    monkeypatch.setattr('sys.stdout', StringIO())
    main()
    assert 'Заметка 1' in sys.stdout.getvalue()
    assert 'Заметка 2' in sys.stdout.getvalue()

def test_delete(monkeypatch):
    # Добавляем две заметки
    monkeypatch.setattr('sys.argv', ['notes_cli.py', 'add', 'Заметка 1'])
    monkeypatch.setattr('sys.stdout', StringIO())
    main()
    assert 'Заметка добавлена: Заметка 1' in sys.stdout.getvalue()

    monkeypatch.setattr('sys.argv', ['notes_cli.py', 'add', 'Заметка 2'])
    monkeypatch.setattr('sys.stdout', StringIO())
    main()
    assert 'Заметка добавлена: Заметка 2' in sys.stdout.getvalue()

    # Удаляем заметку по индексу 1
    monkeypatch.setattr('sys.argv', ['notes_cli.py', 'delete', '1'])
    monkeypatch.setattr('sys.stdout', StringIO())
    main()
    assert 'Заметка 1' in sys.stdout.getvalue()