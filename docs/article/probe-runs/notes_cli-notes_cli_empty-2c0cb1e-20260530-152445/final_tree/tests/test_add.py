import json
import os
from notes import add_note

def test_add_note():
    # Удалить существующий файл заметок, если он есть
    if os.path.exists('notes.json'):
        os.remove('notes.json')

    # Добавить новую заметку
    add_note('Тестовая заметка')

    # Проверить, что файл создан и содержит правильную заметку
    with open('notes.json', 'r') as f:
        notes = json.load(f)
    assert len(notes) == 1
    assert notes[0]['text'] == 'Тестовая заметка'
    assert notes[0]['label'] == 1