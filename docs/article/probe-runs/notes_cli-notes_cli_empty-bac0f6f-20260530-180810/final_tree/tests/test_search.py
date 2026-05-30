import pytest
from notes import add, search

def test_search_empty():
    results = search('ключевое слово')
    assert len(results) == 0

def test_search_single_note():
    add('Заметка с ключевым словом')
    results = search('ключевое слово')
    assert len(results) == 1
    assert results[0] == 'Заметка с ключевым словом'

def test_search_multiple_notes():
    add('Заметка 1')
    add('Заметка 2 с ключевым словом')
    add('Заметка 3')
    results = search('ключевое слово')
    assert len(results) == 1
    assert results[0] == 'Заметка 2 с ключевым словом'

def test_search_case_insensitive():
    add('Заметка в нижнем регистре')
    results = search('нижнем регистре')
    assert len(results) == 1
    assert results[0] == 'Заметка в нижнем регистре'

def test_search_partial_match():
    add('Заметка с ключевым словом')
    results = search('ключевое')
    assert len(results) == 1
    assert results[0] == 'Заметка с ключевым словом'