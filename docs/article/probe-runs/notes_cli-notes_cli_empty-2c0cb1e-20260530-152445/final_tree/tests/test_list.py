import json
import os
from notes import add_note, list_notes

def capture_output(func):
    import io
    import sys
    old_stdout = sys.stdout
    new_stdout = io.StringIO()
    sys.stdout = new_stdout
    func()
    sys.stdout = old_stdout
    return new_stdout.getvalue()

def test_list_notes():
    # Удалить существующий файл заметок, если он есть
    if os.path.exists('notes.json'):
        os.remove('notes.json')

    # Добавить новую заметку
    add_note('Тестовая заметка 1')
    add_note('Тестовая заметка 2')

    # Проверить, что список заметок содержит правильные заметки
    captured_output = capture_output(list_notes)
    assert 'Тестовая заметка 1 (метка: 1)' in captured_output
    assert 'Тестовая заметка 2 (метка: 2)' in captured_output