import pytest
import sys
from io import StringIO
from contextlib import redirect_stdout
from cli import main

def test_add_command(capsys):
    sys.argv = ['cli.py', 'add', 'Тестовая заметка']
    with redirect_stdout(StringIO()) as captured_output:
        main()
    assert captured_output.getvalue().strip() == "Заметка добавлена: Тестовая заметка"

def test_list_command(capsys):
    sys.argv = ['cli.py', 'list']
    with redirect_stdout(StringIO()) as captured_output:
        main()
    assert captured_output.getvalue().strip() == "0: Тестовая заметка"

def test_search_command(capsys):
    sys.argv = ['cli.py', 'search', 'Тестовая']
    with redirect_stdout(StringIO()) as captured_output:
        main()
    assert captured_output.getvalue().strip() == "0: Тестовая заметка"

def test_delete_command(capsys):
    sys.argv = ['cli.py', 'delete', '0']
    with redirect_stdout(StringIO()) as captured_output:
        main()
    assert captured_output.getvalue().strip() == "Заметка с индексом 0 удалена."