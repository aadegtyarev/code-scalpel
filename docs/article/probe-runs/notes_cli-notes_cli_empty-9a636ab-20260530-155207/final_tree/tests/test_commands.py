import os
import json
import pytest
from main import add, list_notes, search, delete

def test_add():
    # Очищаем хранилище перед тестом
    if os.path.exists('notes.json'):
        os.remove('notes.json')
    
    add("Тестовая заметка")
    notes = load_notes()
    assert len(notes) == 1
    assert notes[0] == "Тестовая заметка"
    
def test_list():
    # Очищаем хранилище перед тестом
    if os.path.exists('notes.json'):
        os.remove('notes.json')
    
    add("Заметка 1")
    add("Заметка 2")
    list_notes()
    # Здесь можно добавить проверку вывода, если это необходимо
    
def test_search():
    # Очищаем хранилище перед тестом
    if os.path.exists('notes.json'):
        os.remove('notes.json')
    
    add("Заметка 1")
    add("Заметка 2")
    search("заметка")
    # Здесь можно добавить проверку вывода, если это необходимо
    
def test_delete():
    # Очищаем хранилище перед тестом
    if os.path.exists('notes.json'):
        os.remove('notes.json')
    
    add("Заметка 1")
    add("Заметка 2")
    delete(1)
    notes = load_notes()
    assert len(notes) == 1
    assert notes[0] == "Заметка 2"
    
def load_notes():
    if not os.path.exists('notes.json'):
        return []
    with open('notes.json', 'r') as f:
        return json.load(f)