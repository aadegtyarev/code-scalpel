import pytest
import json
from notes import add, list_notes, search, delete

@pytest.fixture
def setup_teardown():
    # Удаляем все заметки перед тестом и после
    with open('storage.json', 'w') as file:
        json.dump([], file)
    yield
    with open('storage.json', 'w') as file:
        json.dump([], file)

def test_add_note(setup_teardown):
    add('Позвонить маме')
    notes = list_notes()
    assert len(notes) == 1
    assert notes[0]['note'] == 'Позвонить маме'

def test_list_notes(setup_teardown):
    add('Позвонить маме')
    add('Купить продукты')
    notes = list_notes()
    assert len(notes) == 2
    assert notes[0]['note'] == 'Позвонить маме'
    assert notes[1]['note'] == 'Купить продукты'

def test_search_notes(setup_teardown):
    add('Позвонить маме')
    add('Купить продукты')
    results = search('Позвонить')
    assert len(results) == 1
    assert results[0]['note'] == 'Позвонить маме'

def test_delete_note(setup_teardown):
    add('Позвонить маме')
    delete(1)
    notes = list_notes()
    assert len(notes) == 0