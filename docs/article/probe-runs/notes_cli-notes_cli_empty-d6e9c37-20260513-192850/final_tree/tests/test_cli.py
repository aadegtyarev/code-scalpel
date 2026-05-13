import pytest
from notes_cli.cli import main

def test_add_command(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(['add', 'Пример заметки'])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert 'Добавлена новая заметка: Пример заметки' in captured.out

def test_list_command(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(['list'])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert 'Вывод всех заметок' in captured.out

def test_search_command(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(['search', 'ключевое слово'])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert 'Поиск заметок по ключевому слову: ключевое слово' in captured.out

def test_delete_command(capsys):
    with pytest.raises(SystemExit) as excinfo:
        main(['delete', '1'])
    assert excinfo.value.code == 0
    captured = capsys.readouterr()
    assert 'Удалена заметка с идентификатором: 1' in captured.out